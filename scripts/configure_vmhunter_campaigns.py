"""Root-only opt-in of owner-approved campaigns after normal API deployment.

Never updates Twilio routes, creates a call, restarts the API or changes calling
mode. Only the already attested independent worker's policy is reloaded.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request
from uuid import UUID

ROOT=Path('/etc/unlimited-talk-staging')
STATE=ROOT/'vmhunter-runtime'
CAMPAIGNS=['2bdf5195-0b52-49b1-aecc-0caaf5459e77','c137b9e3-149e-4d0b-b814-3c067258b6b8']

def candidate_policy(previous, campaign_ids=None):
    allowed_previous = (previous.get('version') == 3 and previous.get('campaign_id') == CAMPAIGNS[0]
        or campaign_ids is not None and previous.get('version') == 4
            and isinstance(previous.get('campaign_ids'), list) and 1 <= len(previous['campaign_ids']) <= 20)
    if (not allowed_previous
            or previous.get('scope')!='campaign' or previous.get('mode')!='screen'
            or previous.get('agent_ids')!=[] or previous.get('test_numbers')!=[]
            or previous.get('audio_approved') is not True or previous.get('screening_approved') is not True):
        raise ValueError('Expected approved CHIN LIST campaign policy')
    selected = CAMPAIGNS if campaign_ids is None else campaign_ids
    if not isinstance(selected, list) or not 1 <= len(selected) <= 20:
        raise ValueError('Explicit approved campaign identifiers required')
    normalized = [str(UUID(value)) for value in selected]
    if len(set(normalized)) != len(normalized):
        raise ValueError('Duplicate campaign identifiers')
    result=dict(previous);result.pop('campaign_id', None)
    result.update(version=4,campaign_ids=normalized,enabled=True)
    return result

def run(args,*,data=None,timeout=90):
    r=subprocess.run(args,input=data,text=True,capture_output=True,timeout=timeout)
    if r.returncode:raise RuntimeError('Campaign configuration operation failed')
    return r.stdout.strip()

def write_policy(raw):
    path=ROOT/'vmhunter-campaign-policy.json'
    fd=os.open(path,os.O_WRONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'wb') as f:f.write(raw);f.truncate();f.flush();os.fsync(f.fileno())

def health(revision):
    with urllib.request.urlopen('http://127.0.0.1:8110/health/ready',timeout=5) as r:value=json.load(r)
    assert value['revision']==revision and value['calling_enabled'] and value['migration']=='0012_incoming_runtime'
    return value

def apply(revision, campaign_ids=None):
    assert os.geteuid()==0 and re.fullmatch('[a-f0-9]{40}',revision)
    with open('/run/lock/unlimited-talk-staging-deploy.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        release=Path('/srv/unlimited-talk-staging/current').resolve()
        api_revision=release.name.removeprefix('git-')
        assert release.name=='git-'+api_revision
        assert api_revision in {'35b4ba8f076b9ead2712aed239656a8423eb09ff','36a451a4e974dc0a8ff80bbe5540806f57fa3c6f',revision}
        health(api_revision)
        receipt_path=Path('/root/vmhunter-worker-'+revision[:7]+'/approved-image.json')
        assert receipt_path.stat().st_uid==0 and receipt_path.stat().st_mode&0o077==0
        receipt=json.loads(receipt_path.read_text())
        config=json.loads((STATE/'compose.json').read_text())
        assert receipt['revision']==revision and config['services']['vmhunter']['image']==receipt['image']
        labels=json.loads(run(['docker','image','inspect',receipt['image'],'--format','{{json .Config.Labels}}']))
        assert labels['org.opencontainers.image.revision']==revision and labels['io.unlimitedtalk.component']=='vmhunter-worker'
        path=ROOT/'vmhunter-campaign-policy.json';original=path.read_bytes();previous=json.loads(original)
        candidate=candidate_policy(previous, campaign_ids)
        base=['docker','compose','--project-directory',str(release),'--env-file',str(release/'.env'),'-f',str(release/'compose.managed.yaml')]
        check='''import json,sys
from app.database import make_engine
from app.identity.service import query
from app.telephony.vmhunter import Pilot
value=json.loads(sys.stdin.read());pilot=Pilot.parse(value)
engine=make_engine()
with engine.connect() as db:
 query(db,'SET TRANSACTION READ ONLY')
 query(db,"SET LOCAL statement_timeout='3000ms'")
 rows=[dict(r) for r in query(db,"""SELECT c.id,c.name,c.is_active,
  (SELECT s.enabled FROM staging.voice_campaign_settings s WHERE s.campaign_id=c.id) AS dialer_enabled,
  (SELECT count(*) FROM staging.campaign_agents a JOIN staging.identity_users u ON u.id=a.user_id AND u.is_active WHERE a.campaign_id=c.id AND a.is_active) AS active_assigned_users
  FROM staging.campaigns c WHERE c.id=ANY(CAST(:ids AS uuid[])) ORDER BY c.name""",ids=[str(c) for c in pilot.campaigns]).mappings()]
assert len(rows)==len(pilot.campaigns) and all(r['is_active'] and r['dialer_enabled'] and r['active_assigned_users']>0 for r in rows)
print(json.dumps({'campaigns':rows},default=str));engine.dispose()
'''
        # Code and JSON are separate stdin inputs to avoid shell interpolation.
        probe='import sys,io\nprogram='+repr(check)+'\nsys.stdin=io.StringIO('+repr(json.dumps(candidate))+')\nexec(program)'
        proof=json.loads(run([*base,'exec','-T','api','python','-'],data=probe,timeout=45))
        vm=['docker','compose','--project-directory',str(STATE),'--env-file',str(release/'.env'),'-f',str(STATE/'compose.json')]
        disabled=dict(previous);disabled['enabled']=False
        write_policy((json.dumps(disabled)+'\n').encode())
        time.sleep(20) # Drain nine-second jobs plus bounded cleanup/database work.
        try:
            write_policy((json.dumps(candidate)+'\n').encode())
            run([*vm,'up','-d','--pull','never','--force-recreate','--wait','--wait-timeout','60'])
            verify='''import json,urllib.request
from app.telephony.vmhunter_screen import configured
pilot=configured();assert pilot and pilot.enabled and pilot.scope=='campaign'
assert {str(c) for c in pilot.campaigns}==set('''+repr(candidate['campaign_ids'])+''')
with urllib.request.urlopen('http://vmhunter:8080/health/live',timeout=3) as r:state=json.load(r)
assert state['accepting'] is True
print(json.dumps({'campaign_policy_verified':True,'worker':state}))
'''
            result=json.loads(run([*base,'exec','-T','api','python','-'],data=verify,timeout=45))
            health(api_revision)
        except Exception:
            write_policy(original)
            run([*vm,'up','-d','--pull','never','--force-recreate','--wait','--wait-timeout','60'])
            raise
        print(json.dumps(dict(worker_revision=revision,api_revision=api_revision,**proof,**result,all_assigned_agents=True,ordinary_calls_enabled=True,api_restarted=False,quota=result['worker'].get('quota'),concurrent_analyses=2)),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('revision');p.add_argument('--campaign-id',action='append');a=p.parse_args()
    try:apply(a.revision,a.campaign_id)
    except Exception as error:print(json.dumps({'campaign_activation':'stopped','error_type':type(error).__name__}),flush=True);raise SystemExit(1)
