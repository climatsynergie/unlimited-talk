"""Root operator switch for the attested browser delivery's frozen test profile.

No token, call, number routing, migration or provider write is performed here.
The immutable release/template stays webhooks_only; disable uses that base.
"""
import argparse
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import urllib.request

ROOT=Path('/etc/unlimited-talk-staging')
BASE=Path('/srv/unlimited-talk-staging')
OVERRIDE=ROOT/'voice-controlled-test.yaml'
OVERRIDE_BYTES=(json.dumps({'services':{'api':{'environment':{'COMMUNICATIONS_MODE':'controlled_test'}}}},sort_keys=True)+'\n').encode()


def run(args, *, data=None, timeout=90):
    result=subprocess.run(args,input=data,text=True,capture_output=True,timeout=timeout)
    if result.returncode:raise RuntimeError('Operator command failed')
    return result.stdout


def valid_revision(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{40}',value):raise ValueError('Full revision required')
    return value


def protected(path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1 or info.st_mode&0o022:
        raise ValueError('Protected file required')


def atomic(path,data):
    if path.exists() or path.is_symlink():protected(path)
    tmp=path.with_name('.'+path.name+'.'+str(os.getpid()))
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data);stream.flush();os.fchmod(stream.fileno(),0o600);os.fsync(stream.fileno())
        os.replace(tmp,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:tmp.unlink(missing_ok=True)


def safe_config(base,candidate):
    expected=copy.deepcopy(base)
    if expected.get('name')!='unlimited-talk-staging-managed':raise ValueError('Wrong project')
    if expected['services']['api']['environment']['COMMUNICATIONS_MODE']!='webhooks_only':raise ValueError('Wrong base mode')
    expected['services']['api']['environment']['COMMUNICATIONS_MODE']='controlled_test'
    if candidate!=expected:raise ValueError('Only the API test mode may change')


def browser_labels(labels,revision):
    required={'org.opencontainers.image.source':'https://github.com/climatsynergie/unlimited-talk',
              'org.opencontainers.image.revision':valid_revision(revision),
              'io.unlimitedtalk.schema':'0008_recordings','io.unlimitedtalk.voice-browser':'1',
              'io.unlimitedtalk.voice-runtime':'1','io.unlimitedtalk.voice-archive':'1'}
    if any(labels.get(key)!=value for key,value in required.items()):raise ValueError('Browser delivery required')


def health(revision):
    with urllib.request.urlopen('http://127.0.0.1:8110/health/ready',timeout=10) as response:value=json.load(response)
    if (value.get('status')!='ready' or value.get('revision')!=revision or value.get('migration')!='0008_recordings'
            or value.get('communications') not in {'webhooks_only','controlled_test'}):raise ValueError('Unexpected runtime')
    if value.get('calling_enabled') is not (value['communications']=='controlled_test'):raise ValueError('Ambiguous mode')
    return value


def operate(action,revision):
    valid_revision(revision)
    if os.geteuid()!=0:raise ValueError('Root required')
    os.umask(0o077)
    fd=os.open('/run/lock/unlimited-talk-staging-deploy.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        release=(BASE/'current').resolve(strict=True)
        if release.parent!=BASE/'releases' or release.name!='git-'+revision:raise ValueError('Unexpected current release')
        before=health(revision)
        command=['docker','compose','--project-directory',str(release),'--env-file',str(release/'.env'),'-f',str(release/'compose.managed.yaml')]
        base=json.loads(run([*command,'config','--format','json']))
        if (base.get('name')!='unlimited-talk-staging-managed'
                or base['services']['api']['environment']['COMMUNICATIONS_MODE']!='webhooks_only'):
            raise ValueError('The immutable release must retain its closed base mode')
        protected(release/'deployment.json')
        manifest=json.loads((release/'deployment.json').read_text())
        image=base['services']['api']['image']
        if manifest!={'revision':revision,'image':image} or not re.fullmatch('ghcr.io/climatsynergie/unlimited-talk-api@sha256:[a-f0-9]{64}',image):raise ValueError('Immutable image required')
        api_id=run([*command,'ps','-q','api']).strip()
        actual=json.loads(run(['docker','inspect',api_id]))[0]
        browser_labels(actual['Config']['Labels'],revision)
        if actual['Config']['Image']!=image:raise ValueError('Running image mismatch')
        if action=='check':return {'revision':revision,'calling_enabled':before['calling_enabled']}
        if action=='enable' and not before['calling_enabled']:
            for worker in ('voice-reconciler','voice-archiver'):
                identifier=run([*command,'ps','-q',worker]).strip()
                row=json.loads(run(['docker','inspect',identifier]))[0]
                if (row['Config']['Image']!=image or row['State'].get('Health',{}).get('Status')!='healthy'
                        or not row['State']['Running'] or row['State'].get('OOMKilled')):raise ValueError('Recovery workers must be healthy')
            proof=ROOT/'recording-runtime-verified.json';protected(proof)
            evidence=json.loads(proof.read_text())
            if (evidence.get('revision')!=revision or evidence.get('schema')!='0008_recordings'
                    or evidence.get('worker_healthy') is not True):raise ValueError('Verify this deployed archive runtime first')
            if not all(evidence.get(k) is True for k in ('private_database_tls','runtime_role','append_only_jobs','provider_read_gateway','private_storage_access')):
                raise ValueError('Archive verification required')
            code='''
import json
from sqlalchemy import text
from app.database import make_engine
from app.telephony.configuration import load_profile
from app.contacts.storage import client
profile=load_profile();assert profile is not None
engine=make_engine()
try:
 with engine.connect() as db:
  db.execute(text('SET TRANSACTION READ ONLY'))
  active=db.execute(text("SELECT count(*) FROM staging.voice_intents WHERE state IN ('reserved','authorized','ringing','answered') AND (state<>'reserved' OR expires_at>clock_timestamp())")).scalar_one()
 assert engine.pool.checkedout()==0
 transport,bucket=client();assert transport.head_bucket(Bucket=bucket)['ResponseMetadata']['HTTPStatusCode']==200
 print(json.dumps({'active':active,'storage':True}))
finally:engine.dispose()
'''
            ready=json.loads(run([*command,'exec','-T','api','python','-'],data=code))
            if ready!={'active':0,'storage':True}:raise ValueError('Finish the existing reservation first')
            tools=Path('/root/unlimited-talk-voice-tools')
            for name in ('twilio_voice_signing.py','twilio_voice_application.py'):
                tool=tools/name;protected(tool)
                verified=json.loads(run(['python3',str(tool),'check']))
                if verified.get('state')!='verified':raise ValueError('Provider configuration must be verified')
                if name=='twilio_voice_signing.py' and verified.get('rule_applied') is not True:raise ValueError('Scoped signing rule required')
        if action=='enable':
            if OVERRIDE.exists() or OVERRIDE.is_symlink():
                protected(OVERRIDE)
                if OVERRIDE.read_bytes()!=OVERRIDE_BYTES:raise ValueError('Unexpected mode override')
            else:atomic(OVERRIDE,OVERRIDE_BYTES)
            selected=[*command,'-f',str(OVERRIDE)]
            safe_config(base,json.loads(run([*selected,'config','--format','json'])))
        else:selected=command
        wanted=action=='enable'
        if before['calling_enabled'] is not wanted:
            try:
                run([*selected,'up','-d','--no-deps','--no-build','--pull','never','--wait','--wait-timeout','120','api'],timeout=160)
                for attempt in range(20):
                    try:
                        after=health(revision)
                        if after['calling_enabled'] is wanted:break
                    except Exception:pass
                    time.sleep(1)
                else:raise RuntimeError('Mode not confirmed')
            except Exception:
                # An enable failure always attempts to restore the closed base.
                # Never restore controlled_test after a failed disable.
                if wanted:run([*command,'up','-d','--no-deps','--no-build','--pull','never','--wait','--wait-timeout','120','api'],timeout=160)
                raise
        result={'revision':revision,'calling_enabled':wanted,'profile':'approved_single_destination',
                'max_call_seconds':180,'provider_calls_created':False}
        atomic(ROOT/'voice-test-mode.json',(json.dumps(result,indent=2)+'\n').encode())
        return result


def main():
    parser=argparse.ArgumentParser(description='Activer ou fermer le seul appel de validation autorisé, sans le lancer.')
    parser.add_argument('action',choices=['check','enable','disable'])
    parser.add_argument('--revision',required=True)
    args=parser.parse_args()
    try:print(json.dumps(operate(args.action,args.revision)))
    except Exception as error:
        print('Voice test control stopped: '+type(error).__name__)
        return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
