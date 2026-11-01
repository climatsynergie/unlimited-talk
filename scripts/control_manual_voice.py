"""Root-only delivery switch; reuse the attested image, never originate calls.

The release remains closed by default. Profile conversion is reversible and
requires no active calls or outstanding legacy archive jobs. Public login uses
the application's sessions, CSRF, roles and administrator MFA.
"""
import argparse
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

from control_voice_test import atomic, protected, run, valid_revision

ROOT = Path('/etc/unlimited-talk-staging')
BASE = Path('/srv/unlimited-talk-staging')
PROFILE = ROOT/'voice-runtime.json'
OVERRIDE = ROOT/'voice-manual.yaml'
SCHEMA = '0010_dialer'
COMMON = {'account_sid','api_key_sid','api_key_secret','twiml_app_sid','shared_key_id',
          'shared_key_secret','public_origin','caller_number'}
OVERRIDE_BYTES = (json.dumps({'services': {'api': {'environment': {'COMMUNICATIONS_MODE': 'manual'}}}}, sort_keys=True)+'\n').encode()


def labels_valid(labels, revision):
    required = {'org.opencontainers.image.source': 'https://github.com/climatsynergie/unlimited-talk',
        'org.opencontainers.image.revision': valid_revision(revision), 'io.unlimitedtalk.schema': SCHEMA,
        'io.unlimitedtalk.voice-runtime': '1', 'io.unlimitedtalk.voice-browser': '1',
        'io.unlimitedtalk.voice-archive': '1', 'io.unlimitedtalk.inbound-config': '1',
        'io.unlimitedtalk.voice-manual': '1', 'io.unlimitedtalk.dialer': '1'}
    if any(labels.get(key) != value for key, value in required.items()):
        raise ValueError('Attested manual Voice delivery required')


def manual_config(base, candidate):
    expected = copy.deepcopy(base)
    if (expected.get('name') != 'unlimited-talk-staging-managed'
            or expected['services']['api']['environment']['COMMUNICATIONS_MODE'] != 'webhooks_only'):
        raise ValueError('Closed release required')
    expected['services']['api']['environment']['COMMUNICATIONS_MODE'] = 'manual'
    if candidate != expected:
        raise ValueError('Only the API calling mode may change')


def converted_profile(value):
    if type(value.get('version')) is not int:
        raise ValueError('Profile version required')
    if value['version'] == 2:
        if (set(value) != COMMON | {'version','mode','max_concurrent_calls','max_duration_seconds'}
                or value['mode'] != 'manual' or type(value['max_concurrent_calls']) is not int
                or not 3 <= value['max_concurrent_calls'] <= 20
                or type(value['max_duration_seconds']) is not int or not 60 <= value['max_duration_seconds'] <= 600):
            raise ValueError('Unexpected manual profile')
        return value
    if set(value) != COMMON | {'version','mode','approved_destination'} or value['version'] != 1 or value['mode'] != 'controlled_test':
        raise ValueError('Unexpected legacy profile')
    return {key: value[key] for key in COMMON} | {
        'version': 2, 'mode': 'manual', 'max_concurrent_calls': 20, 'max_duration_seconds': 600}


def private_profile_write(data):
    protected(PROFILE)
    info = PROFILE.stat()
    if info.st_gid != 10001 or info.st_mode & 0o777 not in {0o440,0o640}:
        raise ValueError('Unexpected profile ownership')
    temporary = PROFILE.with_name('.manual-profile-'+str(os.getpid()))
    fd = os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush()
            os.fchown(stream.fileno(),0,10001); os.fchmod(stream.fileno(),info.st_mode & 0o777); os.fsync(stream.fileno())
        os.replace(temporary, PROFILE)
        directory = os.open(ROOT, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally: temporary.unlink(missing_ok=True)


def health(revision):
    with urllib.request.urlopen('http://127.0.0.1:8110/health/ready',timeout=10) as response:
        result = json.load(response)
    if (result.get('status') != 'ready' or result.get('revision') != revision or result.get('migration') != SCHEMA
            or result.get('communications') not in {'webhooks_only','manual'}
            or result.get('calling_enabled') is not (result['communications']=='manual')):
        raise ValueError('Unexpected deployed runtime')
    return result


def wait_health(revision, enabled):
    # The gateway briefly caches Docker DNS when the API container is replaced.
    for attempt in range(20):
        try:
            result = health(revision)
            if result['calling_enabled'] is enabled:
                return result
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError('Runtime mode not confirmed')


def status_code(url, *, data=None):
    request = urllib.request.Request(url, data=data)
    try:
        response = urllib.request.urlopen(request,timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status


def public_caddy(original):
    line = '\t\t\timport /etc/caddy/staging-access.caddy'
    marker = '\t\t\t# Application sessions protect business APIs.'
    replacement = marker+'\n\t\t\t@unlimited_talk_internal path /health/* /api/system\n\t\t\trespond @unlimited_talk_internal 404'
    if marker in original:
        if original.count(replacement) != 1 or line in original:
            raise ValueError('Unexpected public access policy')
        return original
    if original.count(line) != 1:
        raise ValueError('Expected one perimeter policy')
    return original.replace(line,replacement)


def runtime_probe(command, *, manual=False, idle=False):
    code = '''
import json,os
from sqlalchemy import text
from app.database import make_engine
from app.telephony.configuration import load_profile
from app.telephony.twilio_voice import ManualVoiceProfile
from app.contacts.storage import client
profile=load_profile(); assert profile is not None
engine=make_engine()
try:
 with engine.connect() as db:
  db.execute(text('SET TRANSACTION READ ONLY'))
  assert db.execute(text('SELECT version_num FROM staging.alembic_version')).scalar_one()=='0010_dialer'
  assert db.execute(text('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()')).scalar_one()
  assert db.execute(text('SELECT current_user')).scalar_one()=='ut_staging_runtime'
  assert not db.execute(text("SELECT pg_has_role(current_user,'ut_staging_migrator','MEMBER')")).scalar_one()
  assert not db.execute(text("SELECT has_table_privilege(current_user,'staging.voice_archive_jobs','DELETE')")).scalar_one()
  active=db.execute(text("SELECT count(*) FROM staging.voice_intents WHERE state IN ('reserved','authorized','ringing','answered') AND (state<>'reserved' OR expires_at>clock_timestamp())")).scalar_one()
  pending=db.execute(text("SELECT count(*) FROM staging.voice_recordings WHERE state<>'archived'")).scalar_one()
  caller=db.execute(text("SELECT EXISTS(SELECT 1 FROM staging.voice_numbers WHERE account_sid=:account AND number=:number AND voice_enabled AND is_present AND is_active AND verified_at>clock_timestamp()-interval '24 hours')"),dict(account=profile.account_sid,number=profile.caller_number)).scalar_one()
 assert engine.pool.checkedout()==0
 transport,bucket=client(); assert transport.head_bucket(Bucket=bucket)['ResponseMetadata']['HTTPStatusCode']==200
 print(json.dumps({'active':active,'pending_archives':pending,'manual':isinstance(profile,ManualVoiceProfile),
  'storage':True,'tls':True,'runtime_role':True,'profile_valid':True,'caller_verified':caller}))
finally: engine.dispose()
'''
    result = json.loads(run([*command,'exec','-T','api','python','-'],data=code))
    if manual and (result.get('manual') is not True or result.get('caller_verified') is not True):
        raise ValueError('Manual profile required')
    if idle and (result.get('active') != 0 or result.get('pending_archives') != 0):
        raise ValueError('Finish calls and archive jobs before profile conversion')
    return result


def verify_archive(command, revision):
    code = '''
import json,os
from uuid import uuid4
from app.telephony.configuration import load_profile
from app.telephony.twilio_voice import ManualVoiceProfile
from app.telephony.recording_archive import RecordingReader,Job,ArchiveError
from app.telephony.caller_directory import NumberReader
assert os.getuid()==10001 and os.environ['COMMUNICATIONS_MODE']=='recovery_only'
profile=load_profile(); assert isinstance(profile,ManualVoiceProfile)
reader=RecordingReader(profile)
assert reader.transport.base.startswith('http://172.30.8.1:8112/')
try: reader.read(Job('RE'+'0'*32,uuid4(),'CA'+'0'*32,1,2,uuid4(),1))
except ArchiveError as error: assert error.args==('recording_not_available',)
else: raise AssertionError('Dummy recording unexpectedly exists')
numbers=NumberReader(profile).read()
assert any(n['number']==profile.caller_number and n['voice_enabled'] for n in numbers)
print(json.dumps({'gateway':True,'numbers':True}))
'''
    if json.loads(run([*command,'exec','-T','voice-archiver','python','-'],data=code)) != {'gateway':True,'numbers':True}:
        raise ValueError('Recording gateway verification failed')
    runtime_probe(command,manual=True)
    atomic(ROOT/'recording-runtime-verified.json', (json.dumps(dict(revision=revision,schema=SCHEMA,
        worker_healthy=True,private_database_tls=True,runtime_role=True,append_only_jobs=True,
        provider_read_gateway=True,private_storage_access=True))+'\n').encode())


def operate(action, revision):
    valid_revision(revision)
    if os.geteuid() != 0:
        raise ValueError('Root required')
    os.umask(0o077)
    fd = os.open('/run/lock/unlimited-talk-staging-deploy.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        release = (BASE/'current').resolve(strict=True)
        if release.parent != BASE/'releases' or release.name != 'git-'+revision:
            raise ValueError('Unexpected current release')
        before = health(revision)
        command = ['docker','compose','--project-directory',str(release),'--env-file',str(release/'.env'),'-f',str(release/'compose.managed.yaml')]
        base = json.loads(run([*command,'config','--format','json']))
        manual_config(base, {**base, 'services': {**base['services'], 'api': {**base['services']['api'],
            'environment': {**base['services']['api']['environment'], 'COMMUNICATIONS_MODE': 'manual'}}}})
        protected(release/'deployment.json')
        image = base['services']['api']['image']
        if (json.loads((release/'deployment.json').read_text()) != {'revision':revision,'image':image}
                or not re.fullmatch('ghcr.io/climatsynergie/unlimited-talk-api@sha256:[a-f0-9]{64}',image)):
            raise ValueError('Immutable deployment required')
        for name in ('api','voice-reconciler','voice-archiver'):
            identifier = run([*command,'ps','-q',name]).strip()
            row = json.loads(run(['docker','inspect',identifier]))[0]
            labels_valid(row['Config']['Labels'],revision)
            if (row['Config']['Image'] != image or not row['State']['Running'] or row['State'].get('OOMKilled')
                    or row['State'].get('Health',{}).get('Status') != 'healthy'):
                raise ValueError('All Voice services must be healthy on the attested image')
        if action == 'prepare':
            if before['calling_enabled']:
                raise ValueError('Disable calls before profile conversion')
            runtime_probe(command,idle=True)
            protected(PROFILE)
            original = PROFILE.read_bytes()
            value = json.loads(original)
            candidate = converted_profile(value)
            if value != candidate:
                backup = ROOT/('voice-profile-before-manual-'+revision+'.json')
                if backup.exists():
                    protected(backup)
                    if backup.read_bytes() != original:
                        raise ValueError('Unexpected profile backup')
                else: atomic(backup,original)
                try:
                    private_profile_write((json.dumps(candidate)+'\n').encode())
                    run([*command,'up','-d','--no-deps','--no-build','--pull','never','--force-recreate',
                        '--wait','--wait-timeout','120','api','voice-reconciler','voice-archiver'],timeout=160)
                    wait_health(revision,False); runtime_probe(command,manual=True)
                except Exception:
                    private_profile_write(original)
                    run([*command,'up','-d','--no-deps','--no-build','--pull','never','--force-recreate',
                        '--wait','--wait-timeout','120','api','voice-reconciler','voice-archiver'],timeout=160)
                    raise
            verify_archive(command,revision)
        elif action in {'enable','check'}:
            runtime_probe(command,manual=True)
            verify_archive(command,revision)
            if action == 'enable':
                for name in ('twilio_voice_signing.py','twilio_voice_application.py'):
                    tool = Path('/root/unlimited-talk-voice-tools')/name; protected(tool)
                    result = json.loads(run(['python3',str(tool),'check']))
                    if result.get('state') != 'verified' or (name=='twilio_voice_signing.py' and result.get('rule_applied') is not True):
                        raise ValueError('Provider verification required')
                if OVERRIDE.exists():
                    protected(OVERRIDE)
                    if OVERRIDE.read_bytes() != OVERRIDE_BYTES:
                        raise ValueError('Unexpected calling override')
                else: atomic(OVERRIDE,OVERRIDE_BYTES)
                selected = [*command,'-f',str(OVERRIDE)]
                manual_config(base,json.loads(run([*selected,'config','--format','json'])))
                if not before['calling_enabled']:
                    try:
                        run([*selected,'up','-d','--no-deps','--no-build','--pull','never','--wait','--wait-timeout','120','api'],timeout=160)
                        wait_health(revision,True)
                    except Exception:
                        run([*command,'up','-d','--no-deps','--no-build','--pull','never','--wait','--wait-timeout','120','api'],timeout=160)
                        raise
        elif action == 'disable':
            run([*command,'up','-d','--no-deps','--no-build','--pull','never','--wait','--wait-timeout','120','api'],timeout=160)
            wait_health(revision,False)
        elif action == 'public-access':
            local = 'http://127.0.0.1:8110'
            for path, expected in [('/api/auth/me',401),('/api/telephony/calls',401),
                ('/api/telephony/active-calls',401),('/api/telephony/dialer/session',401),('/api/telephony/numbers',401),('/api/campaigns',401),
                ('/api/calendar?start=2026-11-01T00:00:00Z&end=2026-11-02T00:00:00Z',401),('/docs',404),('/openapi.json',404)]:
                if status_code(local+path) != expected:
                    raise ValueError('Application authentication must protect every business API')
            from prepare_voice_runtime import replace_caddy, CADDY
            protected(CADDY); original = CADDY.read_text()
            candidate = public_caddy(original)
            try:
                if candidate != original: replace_caddy(candidate)
                for path, expected in [('/connexion',200),('/invitation',200),('/api/auth/me',401),
                    ('/api/telephony/calls',401),('/api/system',404),('/health/ready',404)]:
                    if status_code('https://staging.unlimitedtalkapp.com'+path) != expected:
                        raise ValueError('Public access verification failed')
                if status_code('https://staging.unlimitedtalkapp.com/api/telephony/twilio/probe',data=b'') != 403:
                    raise ValueError('Provider signature protection required')
            except Exception:
                if candidate != original: replace_caddy(original)
                raise
        result = {'revision':revision,'action':action,'calling_enabled':health(revision)['calling_enabled'],
                  'provider_calls_created':False}
        atomic(ROOT/'manual-delivery-status.json',(json.dumps(result)+'\n').encode())
        return result


def main():
    parser = argparse.ArgumentParser(description='Préparer les appels agents et la connexion publique, sans lancer d’appel.')
    parser.add_argument('action', choices=['prepare','check','enable','disable','public-access'])
    parser.add_argument('--revision',required=True)
    args = parser.parse_args()
    try: print(json.dumps(operate(args.action,args.revision)))
    except Exception as error:
        print('Manual Voice control stopped: '+type(error).__name__)
        return 1
    return 0


if __name__=='__main__': raise SystemExit(main())
