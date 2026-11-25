"""Root-only independently attested media-worker rollout. Never restarts the API.

The ordinary call flow stays available. No phone call is created here. Failed
historical cleanup is acknowledged only after a verified-TLS provider read proves
that exact child call terminal; the journal remains append-only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request

ROOT=Path('/etc/unlimited-talk-staging')
STATE=ROOT/'vmhunter-runtime'
REPOSITORY='climatsynergie/unlimited-talk'
PACKAGE='ghcr.io/'+REPOSITORY+'-api'
API_BASE='36a451a4e974dc0a8ff80bbe5540806f57fa3c6f'


def run(args,*,data=None,env=None,timeout=120):
 p=subprocess.run(args,input=data,text=True,capture_output=True,env=env,timeout=timeout)
 if p.returncode:raise RuntimeError('Worker operation failed: '+args[0]+' '+args[1])
 return p.stdout.strip()


def github(path):
 req=urllib.request.Request('https://api.github.com/repos/'+REPOSITORY+'/'+path,headers={'User-Agent':'UnlimitedTalks-owner-authorized-worker-release','Accept':'application/vnd.github+json'})
 with urllib.request.urlopen(req,timeout=20) as response:return json.load(response)


def verify(revision):
 assert re.fullmatch('[a-f0-9]{40}',revision)
 result=github('actions/workflows/vmhunter-worker.yml/runs?head_sha='+revision+'&branch=main&status=success')
 assert any(r['head_sha']==revision and r['head_branch']=='main' and r['conclusion']=='success' for r in result['workflow_runs'])
 folder=Path('/root/vmhunter-worker-'+revision[:7]);folder.mkdir(mode=0o700,exist_ok=True)
 tag=PACKAGE+':vmhunter-git-'+revision
 run(['docker','pull',tag])
 image=json.loads(run(['docker','image','inspect',tag]))[0]
 labels=image['Config']['Labels']
 assert labels['org.opencontainers.image.revision']==revision
 assert labels['org.opencontainers.image.source']=='https://github.com/'+REPOSITORY
 assert labels['io.unlimitedtalk.component']=='vmhunter-worker'
 assert labels['io.unlimitedtalk.vmhunter.api-base']==API_BASE and labels['io.unlimitedtalk.vmhunter.protocol']=='1'
 reference=next(d for d in image['RepoDigests'] if re.fullmatch(re.escape(PACKAGE)+'@sha256:[a-f0-9]{64}',d))
 bundle=folder/'attestations.jsonl'
 items=github('attestations/'+reference.split('@',1)[1])['attestations'];assert items
 bundle.write_text(''.join(json.dumps(item['bundle'])+'\n' for item in items));bundle.chmod(0o600)
 env=dict(os.environ);env.pop('GH_TOKEN',None);env.pop('GITHUB_TOKEN',None)
 run(['gh','attestation','verify','oci://'+reference,'--repo',REPOSITORY,'--signer-workflow',REPOSITORY+'/.github/workflows/vmhunter-worker.yml','--source-ref','refs/heads/main','--source-digest',revision,'--deny-self-hosted-runners','--bundle',str(bundle)],env=env)
 receipt=dict(revision=revision,image=reference,api_base=API_BASE,protocol=1,component='vmhunter-worker',workflow='vmhunter-worker.yml',bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest())
 path=folder/'approved-image.json';path.write_text(json.dumps(receipt,indent=2)+'\n');path.chmod(0o600)
 print(json.dumps({'worker_provenance_verified':True,**receipt}),flush=True)


def update_policy(enabled):
 path=ROOT/'vmhunter-campaign-policy.json';value=json.loads(path.read_text())
 assert value['version']==3 and value['scope']=='campaign' and value['audio_approved'] and value['screening_approved']
 value['enabled']=enabled
 fd=os.open(path,os.O_WRONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'wb') as f:f.write((json.dumps(value)+'\n').encode());f.truncate();f.flush();os.fsync(f.fileno())


def command(release):
 return ['docker','compose','--project-directory',str(STATE),'--env-file',str(release/'.env'),'-f',str(STATE/'compose.json')]


def recover_terminal_calls(base):
 program='''import asyncio,json
import aiohttp
from app.database import make_engine
from app.identity.service import query
from app.telephony.configuration import load_profile
from app.telephony.service import event
from app.telephony import vmhunter as vm
async def main():
 profile=load_profile();engine=make_engine();verified=0
 with engine.connect() as db:
  query(db,'SET TRANSACTION READ ONLY')
  claims=[dict(r) for r in query(db,"""SELECT i.id,i.child_call_sid,c.details FROM staging.voice_intents i
   JOIN staging.voice_events c ON c.intent_id=i.id AND c.kind='vmhunter.claim'
   WHERE i.account_sid=:account AND i.campaign_id=:campaign AND i.state IN ('finished','cancelled','expired')
   AND NOT EXISTS(SELECT 1 FROM staging.voice_events r WHERE r.intent_id=i.id AND r.kind='vmhunter.result' AND r.details->>'stream_stop_confirmed'='true')
   LIMIT 10""",account=profile.account_sid,campaign=vm.PILOT_CAMPAIGN).mappings()]
 async with aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=5)) as session:
  for row in claims:
   child=row['child_call_sid'];nonce=row['details']['nonce']
   from app.telephony.twilio_voice import sid
   assert sid(child,'CA') and row['details']['call_sid']==child
   url='https://api.twilio.com/2010-04-01/Accounts/'+profile.account_sid+'/Calls/'+child+'.json'
   async with session.get(url,auth=aiohttp.BasicAuth(profile.api_key_sid,profile.api_key_secret),allow_redirects=False) as response:
    assert response.status==200
    value=await response.json()
   assert value['sid']==child and value['account_sid']==profile.account_sid
   assert value['status'] in {'completed','busy','no-answer','failed','canceled'},'Never clear a live or unverified stream'
   with engine.begin() as db:
    event(db,row['id'],'vmhunter.cleanup_verified',dict(call_sid=child,nonce=nonce,
       stream_stop_confirmed=True,provider_status=value['status'],source='owner-authorized-root-recovery'))
   verified+=1
 engine.dispose();print(json.dumps({'terminal_cleanup_verified':verified,'history_preserved':True,'real_calls_created':0}))
asyncio.run(main())
'''
 print(run([*base,'exec','-T','vmhunter','python','-'],data=program,timeout=60),flush=True)


def rollout(revision):
 import fcntl
 receipt_path=Path('/root/vmhunter-worker-'+revision[:7]+'/approved-image.json')
 receipt=json.loads(receipt_path.read_text())
 assert receipt['revision']==revision and receipt['api_base']==API_BASE and receipt['component']=='vmhunter-worker'
 assert receipt_path.stat().st_uid==0 and receipt_path.stat().st_mode&0o077==0
 with open('/run/lock/unlimited-talk-staging-deploy.lock','a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  release=Path('/srv/unlimited-talk-staging/current').resolve();assert release.name=='git-'+API_BASE
  import urllib.request
  with urllib.request.urlopen('http://127.0.0.1:8110/health/ready',timeout=5) as response:health=json.load(response)
  assert health['calling_enabled'] and health['revision']==API_BASE
  base=command(release)
  update_policy(False)
  time.sleep(10) # Let the bounded nine-second jobs drain; ordinary calls continue.
  recover_terminal_calls(base)
  path=STATE/'compose.json';original=path.read_bytes();candidate=json.loads(original)
  assert set(candidate['services'])=={'vmhunter'}
  candidate['services']['vmhunter']['image']=receipt['image']
  path.write_text(json.dumps(candidate,indent=2)+'\n');path.chmod(0o600)
  try:
   run([*base,'up','-d','--pull','never','--force-recreate','--wait','--wait-timeout','60'],timeout=90)
   update_policy(True)
   run([*base,'up','-d','--pull','never','--force-recreate','--wait','--wait-timeout','60'],timeout=90)
   with urllib.request.urlopen('http://127.0.0.1:8110/health/ready',timeout=5) as response:after=json.load(response)
   assert after['calling_enabled'] and after['revision']==API_BASE
  except Exception:
   update_policy(False);path.write_bytes(original)
   run([*base,'up','-d','--pull','never','--force-recreate','--wait','--wait-timeout','60'],timeout=90)
   raise
  print(json.dumps(dict(worker_revision=revision,worker_image=receipt['image'],api_revision=API_BASE,api_restarted=False,ordinary_calls_enabled=True,vmhunter_enabled=True)),flush=True)


def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['verify','rollout','disable']);p.add_argument('revision',nargs='?');a=p.parse_args()
 assert os.geteuid()==0;os.umask(0o077)
 if a.action=='disable':update_policy(False);print('VM filtering disabled; ordinary calls unchanged');return
 assert isinstance(a.revision,str) and re.fullmatch('[a-f0-9]{40}',a.revision)
 {'verify':verify,'rollout':rollout}[a.action](a.revision)

if __name__=='__main__':
 try:main()
 except Exception as error:print(json.dumps({'worker_operation':'stopped','error_type':type(error).__name__}),flush=True);raise SystemExit(1)
