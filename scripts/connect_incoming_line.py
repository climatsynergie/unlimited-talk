"""Root-only, selected-number routing with a preserved provider snapshot.

No number purchase, call, SMS, trunk edit or account-wide route change. A lost
POST acknowledgement is resolved by GET before retrying. Configuration is data;
all incoming tables must already exist through the attested Alembic migration.
"""
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import re
from urllib.parse import urlencode
import urllib.request
from uuid import UUID
from control_voice_test import atomic,protected,run,valid_revision
from control_manual_voice import health
from staging_twilio_preflight import NoRedirect

ROOT=Path('/etc/unlimited-talk-staging')
BASE=Path('/srv/unlimited-talk-staging')
FIELDS={'voice_url':'VoiceUrl','voice_method':'VoiceMethod','voice_application_sid':'VoiceApplicationSid',
        'voice_fallback_url':'VoiceFallbackUrl','voice_fallback_method':'VoiceFallbackMethod',
        'status_callback':'StatusCallback','status_callback_method':'StatusCallbackMethod','trunk_sid':'TrunkSid'}


def routes(number):
    result={key:number.get(key) or '' for key in FIELDS}
    if any(not isinstance(value,str) or len(value)>2048 for value in result.values()):raise ValueError('Invalid provider route')
    return result


def desired(origin):
    if not re.fullmatch(r'https://[a-z0-9.-]+',origin):raise ValueError('Canonical HTTPS origin required')
    return dict(voice_url=origin+'/api/telephony/twilio/incoming',voice_method='POST',voice_application_sid='',
        voice_fallback_url='',voice_fallback_method='POST',status_callback=origin+'/api/telephony/twilio/incoming-parent-status',
        status_callback_method='POST',trunk_sid='')


def checked(number,account,pn,phone):
    if (not re.fullmatch('AC[0-9a-fA-F]{32}',account) or not re.fullmatch('PN[0-9a-fA-F]{32}',pn)
            or number.get('account_sid')!=account or number.get('sid')!=pn or number.get('phone_number')!=phone
            or number.get('capabilities',{}).get('voice') is not True):raise ValueError('Provider number mismatch')
    return routes(number)


class Provider:
    def __init__(self,profile,pn):
        if not re.fullmatch('PN[0-9a-fA-F]{32}',pn) or not re.fullmatch('AC[0-9a-fA-F]{32}',profile['account_sid']):raise ValueError('Invalid provider identity')
        self.url='https://api.twilio.com/2010-04-01/Accounts/'+profile['account_sid']+'/IncomingPhoneNumbers/'+pn+'.json'
        self.auth=base64.b64encode((profile['api_key_sid']+':'+profile['api_key_secret']).encode()).decode()
    def request(self,method,values=None):
        if method not in {'GET','POST'} or (method=='POST' and set(values or {})!=set(FIELDS)):raise ValueError('Selected-number GET/POST only')
        data=urlencode({FIELDS[k]:v for k,v in values.items()}).encode() if values else None
        request=urllib.request.Request(self.url,data=data,method=method,headers={'Authorization':'Basic '+self.auth,'Accept':'application/json'})
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=15) as response:
            raw=response.read(65537)
            if len(raw)>65536:raise ValueError('Provider response too large')
            return json.loads(raw)


def runtime(revision):
    valid_revision(revision)
    release=(BASE/'current').resolve(strict=True)
    if release.parent!=BASE/'releases' or release.name!='git-'+revision:raise ValueError('Exact deployed release required')
    state=health(revision)
    if state['migration']!='0012_incoming_runtime':raise ValueError('Deploy the incoming migration through CI first')
    command=['docker','compose','--project-directory',str(release),'--env-file',str(release/'.env'),'-f',str(release/'compose.managed.yaml')]
    protected(release/'deployment.json')
    manifest=json.loads((release/'deployment.json').read_text())
    if manifest.get('revision')!=revision:raise ValueError('Release manifest mismatch')
    for name in ('api','voice-reconciler','voice-archiver'):
        identifier=run([*command,'ps','-q',name]).strip()
        item=json.loads(run(['docker','inspect',identifier]))[0];labels=item['Config']['Labels']
        if (item['Config']['Image']!=manifest['image'] or item['State'].get('Health',{}).get('Status')!='healthy'
                or labels.get('org.opencontainers.image.revision')!=revision or labels.get('io.unlimitedtalk.incoming-runtime')!='1'
                or labels.get('org.opencontainers.image.source')!='https://github.com/climatsynergie/unlimited-talk'):
            raise ValueError('Healthy attested incoming runtime required')
    return command


def database(command,action,values):
    code='''import json
from sqlalchemy import text
from app.database import make_engine
from app.telephony.configuration import load_profile
from app.telephony.twilio_voice import ManualVoiceProfile
p=load_profile();assert isinstance(p,ManualVoiceProfile)
v=__VALUES__
engine=make_engine()
try:
 with engine.begin() as db:
  assert db.execute(text('SELECT version_num FROM staging.alembic_version')).scalar_one()=='0012_incoming_runtime'
  q=db.execute(text('SELECT * FROM staging.inbound_queues WHERE id=:queue FOR UPDATE'),v).mappings().one()
  assert q['is_active'] and q['phone']==v['phone'] and q['version']==v['version']
  assert p.account_sid==v['account'] and p.public_origin==v['origin']
  assert db.execute(text("SELECT 1 FROM staging.voice_numbers WHERE provider_sid=:pn AND account_sid=:account AND number=:phone AND voice_enabled AND is_active AND is_present"),v).first()
  if __ACTION__=='inspect':pass
  elif __ACTION__=='connecting':
   old=db.execute(text('SELECT * FROM staging.inbound_lines WHERE queue_id=:queue FOR UPDATE'),v).mappings().first()
   assert old is None or (old['account_sid']==v['account'] and old['provider_sid']==v['pn'] and old['phone']==v['phone'] and old['public_origin']==v['origin'])
   db.execute(text("INSERT INTO staging.inbound_lines(queue_id,account_sid,provider_sid,phone,public_origin,route_state) VALUES (:queue,:account,:pn,:phone,:origin,'connecting') ON CONFLICT(queue_id) DO UPDATE SET route_state='connecting',last_checked_at=clock_timestamp(),last_error=NULL"),v)
  elif __ACTION__ in {'active','disconnected'}:
   assert db.execute(text("UPDATE staging.inbound_lines SET route_state=:state,verified_at=clock_timestamp(),last_checked_at=clock_timestamp(),last_error=NULL WHERE queue_id=:queue AND provider_sid=:pn RETURNING queue_id"),v|{'state':__ACTION__}).first()
  else:raise ValueError('Unknown routing action')
 print(json.dumps({'verified':True}))
finally:engine.dispose()
'''.replace('__VALUES__',repr(values)).replace('__ACTION__',repr(action))
    if json.loads(run([*command,'exec','-T','api','python','-'],data=code))!={'verified':True}:raise ValueError('Database verification failed')


def operate(action,revision,queue,pn):
    queue=str(UUID(queue));valid_revision(revision)
    if os.geteuid()!=0:raise ValueError('Root required')
    command=runtime(revision)
    path=ROOT/('incoming-line-'+queue+'.json')
    profile_path=ROOT/'voice-runtime.json';protected(profile_path)
    profile=json.loads(profile_path.read_text())
    # Credentials stay on the root-owned host and never enter output/arguments.
    provider=Provider(profile,pn)
    current=provider.request('GET')
    before=checked(current,profile['account_sid'],pn,current.get('phone_number'))
    if action=='prepare':
        code="""import json
from sqlalchemy import text
from app.database import make_engine
engine=make_engine()
try:
 with engine.connect() as db:
  db.execute(text('SET TRANSACTION READ ONLY'))
  row=db.execute(text('SELECT version,phone FROM staging.inbound_queues WHERE id=:id AND is_active'),{'id':QUEUE}).mappings().one()
 print(json.dumps(dict(row)))
finally:engine.dispose()
""".replace('QUEUE',repr(queue))
        selected=json.loads(run([*command,'exec','-T','api','python','-'],data=code))
        binding=dict(queue=queue,phone=selected['phone'],version=selected['version'],account=profile['account_sid'],pn=pn,origin=profile['public_origin'])
        checked(current,binding['account'],pn,binding['phone']);database(command,'inspect',binding)
        plan=dict(version=1,binding=binding,previous=before,desired=desired(binding['origin']))
        if path.exists():
            protected(path)
            if json.loads(path.read_text())!=plan:raise ValueError('Existing preserved routing plan differs')
        else:atomic(path,(json.dumps(plan,sort_keys=True)+'\n').encode())
        return {'prepared':True,'phone':binding['phone'],'queue':queue,'provider_changed':False}
    protected(path);plan=json.loads(path.read_text());binding=plan['binding']
    if (binding['queue']!=queue or binding['pn']!=pn or binding['account']!=profile['account_sid']
            or binding['origin']!=profile['public_origin'] or plan['desired']!=desired(binding['origin'])):raise ValueError('Preserved route mismatch')
    checked(current,binding['account'],pn,binding['phone']);database(command,'inspect',binding)
    target=plan['desired'] if action=='connect' else plan['previous']
    source=plan['previous'] if action=='connect' else plan['desired']
    if before not in (source,target):raise ValueError('Provider route changed outside this operation; preserved')
    if action=='connect':database(command,'connecting',binding)
    if before!=target:
        try:provider.request('POST',target)
        except Exception:pass # Resolve an unknown POST acknowledgement by read.
    observed=checked(provider.request('GET'),binding['account'],pn,binding['phone'])
    if observed!=target:raise RuntimeError('Provider route not confirmed; retry with preserved plan')
    database(command,'active' if action=='connect' else 'disconnected',binding)
    return {'connected':action=='connect','phone':binding['phone'],'queue':queue,'other_numbers_unchanged':True}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','connect','restore'])
    parser.add_argument('--revision',required=True);parser.add_argument('--queue',required=True);parser.add_argument('--number-sid',required=True)
    args=parser.parse_args();os.umask(0o077)
    with open('/run/lock/unlimited-talk-staging-deploy.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        print(json.dumps(operate(args.action,args.revision,args.queue,args.number_sid)))
if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit('Incoming routing stopped: '+type(error).__name__) from None
