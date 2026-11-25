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

ROOT=Path('/etc/unlimited-talk-staging')
STATE=ROOT/'vmhunter-runtime'
CAMPAIGNS=['2bdf5195-0b52-49b1-aecc-0caaf5459e77','c137b9e3-149e-4d0b-b814-3c067258b6b8']

def candidate_policy(previous):
    if (previous.get('version')!=3 or previous.get('campaign_id')!=CAMPAIGNS[0]
            or previous.get('scope')!='campaign' or previous.get('mode')!='screen'
            or previous.get('agent_ids')!=[] or previous.get('test_numbers')!=[]
            or previous.get('audio_approved') is not True or previous.get('screening_approved') is not True):
        raise ValueError('Expected approved CHIN LIST campaign policy')
    result=dict(previous);result.pop('campaign_id')
    result.update(version=4,campaign_ids=CAMPAIGNS,enabled=True)
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

def apply(revision):
    assert os.geteuid()==0 and re.fullmatch('[a-f0-9]{40}',revision)
    with open('/run/lock/unlimited-talk-staging-deploy.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        release=Path('/srv/unlimited-talk-staging/current').resolve()
        assert release.name=='git-'+revision
        health(revision)
        receipt_path=Path('/root/vmhunter-worker-'+revision[:7]+'/approved-image.json')
        assert receipt_path.stat().st_uid==0 and receipt_path.stat().st_mode&0o077==0
        receipt=json.loads(receipt_path.read_text())
        config=json.loads((STATE/'compose.json').read_text())
        assert receipt['revision']==revision and config['services']['vmhunter']['image']==receipt['image']
        labels=json.loads(run(['docker','image','inspect',receipt['image'],'--format','{{json .Config.Labels}}']))
        assert labels['org.opencontainers.image.revision']==revision and labels['io.unlimitedtalk.component']=='vmhunter-worker'
        path=ROOT/'vmhunter-campaign-policy.json';original=path.read_bytes();previous=json.loads(original)
        candidate=candidate_policy(previous)
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
  (SELECT count(*) FROM staging.campaign_agents a JOIN staging.identity_users u ON u.id=a.user_id AND u.is_active WHERE a.campaign_id=c.id AND a.is_active) AS active_assigned_users
  FROM staging.campaigns c WHERE c.id=ANY(CAST(:ids AS uuid[])) ORDER BY c.name""",ids=[str(c) for c in pilot.campaigns]).mappings()]
assert len(rows)==2 and all(r['is_active'] and r['active_assigned_users']>0 for r in rows)
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
assert {str(c) for c in pilot.campaigns}==set('''+repr(CAMPAIGNS)+''')
with urllib.request.urlopen('http://vmhunter:8080/health/live',timeout=3) as r:state=json.load(r)
assert state['accepting'] is True
print(json.dumps({'campaign_policy_verified':True,'worker':state}))
'''
            result=json.loads(run([*base,'exec','-T','api','python','-'],data=verify,timeout=45))
            health(revision)
        except Exception:
            write_policy(original)
            run([*vm,'up','-d','--pull','never','--force-recreate','--wait','--wait-timeout','60'])
            raise
        print(json.dumps(dict(revision=revision,**proof,**result,all_assigned_agents=True,ordinary_calls_enabled=True,api_restarted=False,analysis_budget=candidate['max_analyses'],concurrent_analyses=2)),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('revision');a=p.parse_args()
    try:apply(a.revision)
    except Exception as error:print(json.dumps({'campaign_activation':'stopped','error_type':type(error).__name__}),flush=True);raise SystemExit(1)
