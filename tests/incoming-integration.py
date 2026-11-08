"""Real signed HTTP/PG incoming proof; no PSTN, SDK sockets or external I/O."""
from contextlib import asynccontextmanager
from datetime import timedelta
import base64,io,json,os,threading,time,urllib.request,urllib.error,wave
from urllib.parse import urlencode
from uuid import UUID,uuid4
from xml.etree import ElementTree
import uvicorn
from starlette.datastructures import FormData
from twilio.request_validator import RequestValidator
from app.database import make_engine
from app.identity.service import query
from app.identity.security import COOKIE,CSRF_COOKIE,new_token,digest
from app.main import app,lifespan
from app.telephony.twilio_voice import ManualVoiceProfile,webhook_url,incoming_identity
from app.telephony.incoming_settlement import process_once

assert os.environ['DB_HOST']=='db' and os.environ.get('DB_DEPLOYMENT','local')=='local'
assert os.environ['COMMUNICATIONS_MODE']=='disabled'
engine=make_engine()
with engine.connect() as db:
 assert query(db,"SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one()=='synthetic_only'
 assert query(db,'SELECT version_num FROM staging.alembic_version').scalar_one()=='0012_incoming_runtime'
for prefix in ('416','705','902','506','204'):
 for suffix in range(100,200):
  caller='+1'+prefix+'555'+str(suffix).zfill(4)
  with engine.connect() as db:used=query(db,'SELECT 1 FROM staging.inbound_queues WHERE phone=:phone',phone=caller).first()
  if not used:break
 else:continue
 break
else:raise ValueError('Synthetic receiving phone range exhausted')
profile=ManualVoiceProfile('AC'+uuid4().hex,'SK'+'b'*32,'c'*32,'AP'+'d'*32,
 'webhooks_sharedkey_'+'e'*26,'f'*32,'https://voice.example.invalid',caller,3,600)
@asynccontextmanager
async def fixture_lifespan(application):
 async with lifespan(application):
  application.state.voice_profile=profile;application.state.voice_calling_enabled=True
  yield
app.router.lifespan_context=fixture_lifespan
server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=18014,log_level='critical',access_log=False))
thread=threading.Thread(target=server.run,daemon=True);thread.start()
for _ in range(200):
 if server.started:break
 time.sleep(.025)
assert server.started
base='http://127.0.0.1:18014';origin=os.environ['APP_ORIGIN']
def request(method,path,data=None,headers=None,expected=200):
 req=urllib.request.Request(base+path,data=data,headers=headers or {},method=method)
 try:response=urllib.request.urlopen(req,timeout=20)
 except urllib.error.HTTPError as error:response=error
 with response:
  result=response.read();assert response.status==expected,(path,response.status,expected,result[:300])
  return result
class Browser:
 def __init__(self,role='agent'):
  self.id=uuid4();self.token=new_token();self.csrf=new_token()
  with engine.begin() as db:
   query(db,'''INSERT INTO staging.identity_users(id,email,display_name,role,password_hash,mfa_secret)
    VALUES (:id,:email,'Agent réception QA',:role,'unused',:mfa)''',id=self.id,email=str(self.id)+'@example.invalid',role=role,
    mfa=app.state.identity_cipher.encrypt(b'JBSWY3DPEHPK3PXP').decode() if role=='admin' else None)
   query(db,'''INSERT INTO staging.identity_sessions(token_hash,csrf_hash,user_id,mfa_verified,expires_at)
    VALUES (:token,:csrf,:id,true,clock_timestamp()+interval '1 hour')''',id=self.id,token=digest(self.token),csrf=digest(self.csrf))
 def request(self,method,path,body=None,expected=200,raw=False,**headers):
  settings={'Cookie':COOKIE+'='+self.token+'; '+CSRF_COOKIE+'='+self.csrf,'Origin':origin,'X-CSRF-Token':self.csrf,'Content-Type':'application/json',**headers}
  content=request(method,path,json.dumps(body).encode() if body is not None else None,settings,expected)
  return content if raw else json.loads(content)
def signed(kind,identifier=None,fields=None,expected=200,**headers):
 values=FormData([('AccountSid',profile.account_sid),*(fields or {}).items()])
 target=webhook_url(profile,kind,identifier)
 signature=RequestValidator(profile.shared_key_secret).compute_signature(target,values)
 settings={'Content-Type':'application/x-www-form-urlencoded','X-Twilio-Signature':signature,
  'X-Twilio-Webhooks-Signature-Settings':'key='+profile.shared_key_id+',algorithm=HMAC_SHA1',**headers}
 raw=request('POST',target.removeprefix(profile.public_origin),urlencode(values.multi_items()).encode(),settings,expected)
 return ElementTree.fromstring(raw) if expected==200 else raw

def receive(caller):
 sid='CA'+uuid4().hex
 fields=dict(CallSid=sid,From=caller,To=profile.caller_number,Direction='inbound',CallStatus='ringing')
 xml=signed('incoming',fields=fields)
 identifier=UUID(xml.find('Redirect').text.rsplit('/',1)[1])
 return identifier,fields

def step(call):return signed('incoming-step',call[0],call[1])
def offers(call):
 with engine.connect() as db:return [dict(row) for row in query(db,'SELECT * FROM staging.inbound_offers WHERE call_id=:id ORDER BY offered_at,id',id=call[0]).mappings()]
def call_row(call):
 with engine.connect() as db:return dict(query(db,'SELECT * FROM staging.inbound_calls WHERE id=:id',id=call[0]).mappings().one())
def decline(call,offer):
 return signed('incoming-dial-finish',offer['id'],dict(CallSid=call[1]['CallSid'],DialCallSid=offer['child_call_sid'] or 'CA'+uuid4().hex,DialCallStatus='no-answer',DialBridged='false'))
try:
 admin=Browser('admin');agents=[Browser() for _ in range(3)];outsider=Browser()
 number=uuid4();queue=uuid4()
 with engine.begin() as db:
  query(db,'''INSERT INTO staging.voice_numbers(id,account_sid,provider_sid,number,name,country,voice_enabled,verified_at)
   VALUES (:id,:account,:sid,:number,'Ligne QA','CA',true,clock_timestamp())''',id=number,account=profile.account_sid,sid='PN'+uuid4().hex,number=profile.caller_number)
  query(db,'INSERT INTO staging.voice_directory_state(account_sid,synchronized_at) VALUES (:account,clock_timestamp())',account=profile.account_sid)
 admin.request('POST','/api/inbound/queues',dict(id=str(queue),name='Réception QA '+uuid4().hex,phone=profile.caller_number,
  hours=[],agents=[dict(user_id=str(agent.id),mode='mixed') for agent in agents]),201)
 with engine.begin() as db:
  query(db,'''INSERT INTO staging.inbound_lines(queue_id,account_sid,provider_sid,phone,public_origin,route_state,verified_at)
   VALUES (:id,:account,:sid,:phone,:origin,'active',clock_timestamp())''',id=queue,account=profile.account_sid,sid='PN'+uuid4().hex,phone=profile.caller_number,origin=profile.public_origin)
 assert agents[0].request('GET','/api/inbound/reception')['enabled']
 outsider.request('POST','/api/inbound/reception/register',dict(browser_id=str(uuid4())),409)
 # Deployment admission closure rejects new media but preserves terminal-ledger
 # recovery. These signed HTTP requests must not create an active call.
 app.state.voice_calling_enabled=False
 closed_fields=dict(CallSid='CA'+uuid4().hex,From='+16135550100',To=profile.caller_number,Direction='inbound',CallStatus='ringing')
 refused=signed('incoming',fields=closed_fields)
 assert refused.find('Reject').attrib['reason']=='busy'
 assert all(refused.find(verb) is None for verb in ('Say','Record','Dial','Redirect'))
 with engine.connect() as db:
  assert query(db,'SELECT count(*) FROM staging.inbound_calls WHERE parent_call_sid=:sid',sid=closed_fields['CallSid']).scalar_one()==0
 signed('incoming-parent-status',fields={**closed_fields,'CallStatus':'busy','CallDuration':'0'})
 assert process_once(engine,profile)==1 and process_once(engine,profile)==0
 with engine.connect() as db:
  closed=query(db,'SELECT * FROM staging.inbound_calls WHERE parent_call_sid=:sid',sid=closed_fields['CallSid']).mappings().one()
  assert closed['state']=='finished' and closed['followup_id'] is not None
 app.state.voice_calling_enabled=True
 first=receive('+16135550101')
 assert step(first).find('Dial') is None
 app.state.voice_calling_enabled=False
 replay=signed('incoming',fields=first[1]);assert replay.find('Redirect').text.endswith(str(first[0]))
 app.state.voice_calling_enabled=True
 registrations=[]
 for agent in agents:
  reg=agent.request('POST','/api/inbound/reception/register',dict(browser_id=str(uuid4())),201)
  payload=json.loads(base64.urlsafe_b64decode(reg['token'].split('.')[1]+'=='))
  assert payload['grants']['voice']['incoming']['allow'] is True and 'outgoing' not in payload['grants']['voice']
  registrations.append(reg)
  agent.request('PATCH','/api/inbound/reception/'+reg['id'],dict(available=True,media_ready=True))
 offered=step(first);assert offered.find('Dial') is not None
 one=offers(first)[0];owner=agents[0]
 assert one['actor_id']==owner.id and offered.find('Dial').attrib['timeLimit']=='1800'
 assert offered.find('Dial').attrib['record']=='record-from-answer-dual'
 assert step(first).find('Dial') is None and len(offers(first))==1
 path='/api/inbound/reception/offers/'+str(one['id'])
 outsider.request('GET',path,expected=404)
 owner.request('POST',path,dict(registration_id=registrations[1]['id'],accept=True),404)
 child='CA'+uuid4().hex
 child_fields=dict(CallSid=child,ParentCallSid=first[1]['CallSid'],From=profile.caller_number,To='client:'+incoming_identity(UUID(registrations[0]['id'])))
 denied=signed('incoming-agent-answer',one['id'],{**child_fields,'ParentCallSid':'CA'+uuid4().hex})
 assert denied.find('Hangup') is not None
 signed('incoming-agent-status',one['id'],{**child_fields,'CallStatus':'ringing','SequenceNumber':'0'})
 owner.request('POST',path,dict(registration_id=registrations[0]['id'],accept=True))
 assert signed('incoming-agent-answer',one['id'],child_fields).find('Hangup') is None
 assert signed('incoming-agent-answer',one['id'],child_fields).find('Hangup') is None
 assert call_row(first)['state']=='connected'
 # Presence expiry must NEVER release an established call's shared occupancy.
 with engine.begin() as db:query(db,"UPDATE staging.inbound_registrations SET lease_until=clock_timestamp()-interval '1 second' WHERE id=:id",id=UUID(registrations[0]['id']))
 blocked=owner.request('POST','/api/telephony/test/intents',dict(id=str(uuid4()),destination='+16135550104'),409)
 assert 'entrant' in blocked['detail']
 outgoing=agents[2].request('POST','/api/telephony/test/intents',dict(id=str(uuid4()),destination='+16135550105'),201)
 second=receive('+16135550102');assert step(second).find('Dial') is not None
 assert offers(second)[0]['actor_id']==agents[1].id
 third=receive('+16135550103');assert step(third).find('Dial') is None
 with engine.connect() as db:
  total=query(db,"SELECT (SELECT count(*) FROM staging.inbound_offers o JOIN staging.inbound_calls c ON c.id=o.call_id WHERE o.state<>'finished' AND c.account_sid=:account)+(SELECT count(*) FROM staging.voice_intents WHERE state='reserved' AND account_sid=:account)",account=profile.account_sid).scalar_one()
  assert total==3
 signed('incoming-parent-status',fields={**first[1],'CallStatus':'completed'})
 assert offers(first)[0]['state']=='connected'
 signed('incoming-agent-status',one['id'],{**child_fields,'CallStatus':'completed','CallDuration':'45','SequenceNumber':'1'})
 assert offers(first)[0]['state']=='finished' and call_row(first)['outcome']=='answered'
 # A completed agent leg alone is provisional: the final bridge result wins.
 signed('incoming-dial-finish',one['id'],dict(CallSid=first[1]['CallSid'],DialCallSid=child,DialCallStatus='completed',DialBridged='false',DialCallDuration='0'))
 assert call_row(first)['outcome']=='abandoned'
 # Projection is intentionally handled later in the ordinary worker pass.
 assert process_once(engine,profile)==1
 agents[2].request('POST','/api/telephony/test/intents/'+outgoing['intent']['id']+'/cancel',{})
 assert step(third).find('Dial') is not None and offers(third)[0]['actor_id']==agents[2].id
 two=offers(second)[0];decline(second,two)
 assert call_row(second)['state']=='waiting'
 with engine.begin() as db:query(db,"UPDATE staging.inbound_calls SET received_at=clock_timestamp()-interval '65 seconds' WHERE id=:id",id=second[0])
 vm=step(second);assert vm.find('Record') is not None and vm.find('Record').attrib['maxLength']=='120'
 assert step(second).find('Record') is None
 recording_sid='RE'+uuid4().hex
 record_fields=dict(CallSid=second[1]['CallSid'],RecordingSid=recording_sid,RecordingStatus='completed',RecordingSource='RecordVerb',RecordingChannels='1',RecordingDuration='3')
 app.state.voice_calling_enabled=False
 signed('incoming-recording',second[0],record_fields);signed('incoming-recording',second[0],record_fields)
 signed('incoming-recording',third[0],record_fields,403)
 signed('incoming-recording',second[0],{**record_fields,'RecordingSid':'RE'+uuid4().hex,'RecordingChannels':'2'},403)
 signed('incoming-voicemail-finish',second[0],second[1])
 app.state.voice_calling_enabled=True
 assert process_once(engine,profile)==1 and process_once(engine,profile)==0
 with engine.connect() as db:
  assert query(db,'SELECT count(*) FROM staging.inbound_recordings WHERE call_id=:id',id=second[0]).scalar_one()==1
  followup=query(db,'SELECT followup_id FROM staging.inbound_calls WHERE id=:id',id=second[0]).scalar_one()
  assert query(db,'SELECT count(*) FROM staging.inbound_interactions WHERE followup_id=:id',id=followup).scalar_one()==1
 assert agents[1].request('GET','/api/inbound/followups/'+str(followup))['followup']['caller_number']=='+16135550102'

 # Only provider I/O is replaced; upload, integrity verification, private
 # authorization and HTTP Range playback use the real local object store.
 from app.telephony import incoming_archive
 from app.contacts.storage import client as object_client
 from botocore.exceptions import ClientError
 storage,bucket=object_client(multipart=True)
 try:storage.head_bucket(Bucket=bucket)
 except ClientError as error:
  if error.response.get('ResponseMetadata',{}).get('HTTPStatusCode')!=404:raise
  storage.create_bucket(Bucket=bucket)
 from app.telephony.recording_archive import RecordingReader
 audio=io.BytesIO()
 with wave.open(audio,'wb') as wav:
  wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000);wav.writeframes(b'\0'*(3*8000*2))
 content=audio.getvalue()
 def recording_transport(req,limit):
  if req.full_url.endswith('.json'):
   return json.dumps(dict(sid=recording_sid,account_sid=profile.account_sid,call_sid=second[1]['CallSid'],
    status='completed',source='RecordVerb',channels=1,duration='3',encryption_details=None)).encode()
  assert req.full_url.endswith('.wav?RequestedChannels=1')
  return content
 assert incoming_archive.archive_once(engine,profile,RecordingReader(profile,recording_transport))=='archived'
 assert incoming_archive.archive_once(engine,profile,RecordingReader(profile,recording_transport))=='idle'
 audio_path='/api/telephony/recordings/'+recording_sid+'/audio'
 outsider.request('GET',audio_path,expected=404)
 header=agents[1].request('GET',audio_path,expected=206,raw=True,Range='bytes=0-43')
 assert header[:4]==b'RIFF' and header[8:12]==b'WAVE' and len(header)==44
 assert admin.request('GET',audio_path,raw=True)==content
 linked=agents[1].request('GET','/api/inbound/followups/'+str(followup)+'/calls')
 assert linked['items'][0]['recordings'][0]['sid']==recording_sid
 assert linked['items'][0]['recordings'][0]['state']=='archived'
 history=agents[1].request('GET','/api/inbound/queues/'+str(queue)+'/calls')
 assert next(item for item in history['items'] if item['id']==str(second[0]))['recordings'][0]['channels']==1
 outsider.request('GET','/api/inbound/queues/'+str(queue)+'/calls',expected=403)

 decline(third,offers(third)[0]);signed('incoming-parent-status',fields={**third[1],'CallStatus':'completed'})
 process_once(engine,profile)
 # A terminal callback recovers a caller whose initial webhook never persisted.
 recovered_sid='CA'+uuid4().hex
 recovered_fields=dict(CallSid=recovered_sid,From='+16135550109',To=profile.caller_number,Direction='inbound',CallStatus='completed',CallDuration='12')
 signed('incoming-parent-status',fields=recovered_fields)
 assert process_once(engine,profile)==1 and process_once(engine,profile)==0
 with engine.connect() as db:
  recovered=query(db,'SELECT * FROM staging.inbound_calls WHERE parent_call_sid=:sid',sid=recovered_sid).mappings().one()
  assert recovered['followup_id'] is not None and recovered['outcome']=='abandoned'

 # Reconciliation releases uncertain media only after a complete provider read.
 from app.telephony import incoming_recovery
 from app.telephony.reconciliation import ProviderReadError
 recovery_call=receive('+16135550110');step(recovery_call);ro=offers(recovery_call)[0]
 with engine.connect() as db:
  snapshot={'call':call_row(recovery_call),'offers':offers(recovery_call)}
 child_data=dict(sid='CA'+uuid4().hex,account_sid=profile.account_sid,parent_call_sid=recovery_call[1]['CallSid'],
  direction='outbound-dial',status='completed',duration='0',**{'from':profile.caller_number,'to':'client:'+ro['client_identity']})
 parent_data=dict(sid=recovery_call[1]['CallSid'],account_sid=profile.account_sid,direction='inbound',status='in-progress',
  **{'from':recovery_call[1]['From'],'to':profile.caller_number})
 class Provider:
  def _get(self,path):
   if 'Calls.json?' in path:return {'calls':[child_data], 'next_page_uri':None}
   return child_data if child_data['sid'] in path else parent_data
 provider=Provider()
 from app.telephony.reconciliation import ReadOnlyCalls
 # Replace network I/O only. The actual shared endpoint allowlist and provider
 # adapter must be exercised; a fake _get alone can hide refused new endpoints.
 adapter=ReadOnlyCalls(profile,send=lambda request:provider._get(request.full_url.removeprefix('https://api.twilio.com/2010-04-01/Accounts/'+profile.account_sid)))
 observation=incoming_recovery.observe(adapter,snapshot)
 assert incoming_recovery.apply(engine,profile,observation)=='checked'
 assert offers(recovery_call)[0]['state']=='finished' and call_row(recovery_call)['state']=='waiting'
 parent_data['status']='completed'
 assert incoming_recovery.apply(engine,profile,incoming_recovery.observe(adapter,{'call':call_row(recovery_call),'offers':offers(recovery_call)}))=='checked'
 assert call_row(recovery_call)['state']=='finished'
 class Ambiguous(Provider):
  def _get(self,path):
   if 'Calls.json?' in path:return {'calls':[child_data,{**child_data,'sid':'CA'+uuid4().hex}],'next_page_uri':None}
   return super()._get(path)
 try:incoming_recovery.observe(Ambiguous(),snapshot)
 except ProviderReadError:pass
 else:raise AssertionError('Ambiguous provider children must retain occupancy')
 process_once(engine,profile)

 # Twenty agents contend for twenty shared media slots concurrently. Only
 # synthetic signed webhooks/SQL are used; no real SDK or telephone is invoked.
 from concurrent.futures import ThreadPoolExecutor
 from dataclasses import replace
 profile=replace(profile,max_concurrent_calls=20)
 app.state.voice_profile=profile
 extra=[Browser() for _ in range(17)]
 with engine.begin() as db:
  for agent in extra:query(db,'INSERT INTO staging.inbound_queue_agents(queue_id,user_id,mode,is_active,assigned_by) VALUES (:queue,:actor,\'mixed\',true,:admin)',queue=queue,actor=agent.id,admin=admin.id)
  query(db,"UPDATE staging.inbound_offers SET ended_at=ended_at-interval '20 seconds' WHERE call_id IN (SELECT id FROM staging.inbound_calls WHERE account_sid=:account) AND connected_at IS NOT NULL",account=profile.account_sid)
 for agent in agents+extra:
  existing=agent.request('GET','/api/inbound/reception')['registration']
  reg_id=existing['id'] if existing else agent.request('POST','/api/inbound/reception/register',dict(browser_id=str(uuid4())),201)['id']
  agent.request('PATCH','/api/inbound/reception/'+reg_id,dict(available=True,media_ready=True))
 batch=[receive('+1613555'+str(120+i).zfill(4)) for i in range(25)]
 with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(step,batch))
 # A skipped busy actor may become visible on the next queue iteration.
 with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(step,batch))
 with engine.connect() as db:
  offered=query(db,"SELECT count(*),count(DISTINCT actor_id) FROM staging.inbound_offers o JOIN staging.inbound_calls c ON c.id=o.call_id WHERE o.state<>'finished' AND c.account_sid=:account",account=profile.account_sid).one()
  assert tuple(offered)==(20,20),offered
 for item in batch:
  current=offers(item)
  if current:decline(item,current[-1])
  signed('incoming-parent-status',fields={**item[1],'CallStatus':'completed'})
 process_once(engine,profile)
 print('Incoming HTTP/PG: three-agent and 20-agent concurrent admission, recovery, signed offers, privacy, replay, missed follow-up and private mono audio: PASS')
finally:
 server.should_exit=True;thread.join(5);engine.dispose()
