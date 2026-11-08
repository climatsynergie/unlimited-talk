"""Authenticated call budgets cannot be spent by anonymous or already-limited clients."""
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import json,os,threading,time,unittest,urllib.request,urllib.error
from uuid import uuid4
import uvicorn
from fastapi import HTTPException
from app.main import app,lifespan
from app.database import make_engine
from app.identity import service as identity
from app.identity.security import COOKIE,CSRF_COOKIE,digest,new_token
from app.telephony.twilio_voice import ManualVoiceProfile
assert os.environ['DB_HOST']=='db' and os.environ.get('DB_DEPLOYMENT','local')=='local' and os.environ['COMMUNICATIONS_MODE']=='disabled'
engine=make_engine()
with engine.connect() as db:assert identity.query(db,"SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one()=='synthetic_only'
profile=ManualVoiceProfile('AC'+uuid4().hex,'SK'+'b'*32,'c'*32,'AP'+'d'*32,'webhooks_sharedkey_'+'e'*26,'f'*32,'https://voice.example.invalid','+14165550100',20,600)
@asynccontextmanager
async def fixture_lifespan(application):
 async with lifespan(application):
  application.state.voice_profile=profile;application.state.voice_calling_enabled=True
  yield
app.router.lifespan_context=fixture_lifespan
server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=18029,log_level='critical',access_log=False))
thread=threading.Thread(target=server.run,daemon=True);thread.start()
for _ in range(200):
 if server.started:break
 time.sleep(.025)
assert server.started
origin=os.environ['APP_ORIGIN']
class Browser:
 def __init__(self,actor=None):
  self.id=actor or uuid4();self.token=new_token();self.csrf=new_token()
  with engine.begin() as db:
   if actor is None:identity.query(db,"INSERT INTO staging.identity_users(id,email,display_name,role,password_hash) VALUES (:id,:email,'QA budgets','agent','unused')",id=self.id,email=str(self.id)+'@example.invalid')
   identity.query(db,"INSERT INTO staging.identity_sessions(token_hash,csrf_hash,user_id,mfa_verified,expires_at) VALUES (:token,:csrf,:actor,true,clock_timestamp()+interval '1 hour')",token=digest(self.token),csrf=digest(self.csrf),actor=self.id)
 def headers(self):return {'Cookie':COOKIE+'='+self.token+'; '+CSRF_COOKIE+'='+self.csrf,'X-CSRF-Token':self.csrf}
def post(path,body,headers=None):
 request=urllib.request.Request('http://127.0.0.1:18029/api'+path,data=json.dumps(body).encode(),method='POST',headers={'Origin':origin,'Content-Type':'application/json',**(headers or {})})
 try:response=urllib.request.urlopen(request,timeout=15)
 except urllib.error.HTTPError as error:response=error
 with response:return response.status,response.read()
def set_bucket(bucket,count):
 if count==0:
  with engine.begin() as db:identity.query(db,'DELETE FROM staging.identity_rate_limits WHERE bucket=:bucket',bucket=bucket)
  return
 with engine.begin() as db:identity.query(db,"INSERT INTO staging.identity_rate_limits(bucket,attempts,expires_at) VALUES (:bucket,:count,clock_timestamp()+interval '60 seconds') ON CONFLICT(bucket) DO UPDATE SET attempts=excluded.attempts,expires_at=excluded.expires_at",bucket=bucket,count=count)
def count(bucket):
 with engine.connect() as db:return identity.query(db,'SELECT attempts FROM staging.identity_rate_limits WHERE bucket=:bucket',bucket=bucket).scalar_one_or_none() or 0
def reserve(user=None,index=0):return post('/telephony/test/intents',dict(id=str(uuid4()),destination='+1702555'+str(1000+index)),user.headers() if user else {})
with engine.begin() as db:
 identity.query(db,"INSERT INTO staging.voice_numbers(id,account_sid,provider_sid,number,name,country,voice_enabled,verified_at) VALUES (:id,:account,:pn,:phone,'QA budgets','CA',true,clock_timestamp())",id=uuid4(),account=profile.account_sid,pn='PN'+uuid4().hex,phone=profile.caller_number)
 identity.query(db,'INSERT INTO staging.voice_directory_state(account_sid,synchronized_at) VALUES (:account,clock_timestamp())',account=profile.account_sid)
class CallBudgetTests(unittest.TestCase):
 def setUp(self):
  self.user=Browser();set_bucket('voice-global',0);set_bucket('dialer-global',0)
 def test_anonymous_voice_request_does_not_charge_authenticated_budget(self):
  self.assertEqual(reserve()[0],401);self.assertEqual(count('voice-global'),0)
 def test_anonymous_next_request_does_not_charge_authenticated_budget(self):
  status,_=post('/telephony/dialer/next',dict(id=str(uuid4()),browser_id=str(uuid4()),generation=1))
  self.assertEqual(status,401);self.assertEqual(count('dialer-global'),0)
 def test_anonymous_cannot_take_the_last_legitimate_slot(self):
  set_bucket('voice-global',599);self.assertEqual(reserve()[0],401)
  self.assertEqual(reserve(self.user,2)[0],201)
 def test_authenticated_overquota_cannot_drain_other_agents_budget(self):
  set_bucket('voice-reserve:'+digest(str(self.user.id)),30)
  set_bucket('voice-reserve:'+digest(self.user.token),30) # old per-session counter too
  for _ in range(4):self.assertEqual(reserve(self.user,3)[0],429)
  self.assertEqual(count('voice-global'),0)
 def test_new_session_does_not_reset_per_agent_quota(self):
  set_bucket('voice-reserve:'+digest(str(self.user.id)),30)
  second=Browser(self.user.id);self.assertEqual(reserve(second,4)[0],429)
 def test_authenticated_two_actor_requests_do_not_exhaust_pool(self):
  other=Browser()
  with ThreadPoolExecutor(max_workers=2) as pool:
   values=list(pool.map(lambda item:reserve(*item)[0],[(self.user,5),(other,6)]))
  self.assertEqual(sorted(values),[201,201])
 def test_anonymous_global_rejection_does_not_create_unbounded_keys(self):
  operation='qa-flood-'+uuid4().hex;set_bucket('global',0)
  identity.limited(engine,operation,'first',limit=10,seconds=900,global_limit=1)
  for _ in range(5):
   with self.assertRaises(HTTPException) as raised:identity.limited(engine,operation,str(uuid4()),limit=10,seconds=900,global_limit=1)
   self.assertEqual(raised.exception.status_code,429)
  with engine.connect() as db:keys=identity.query(db,"SELECT count(*) FROM staging.identity_rate_limits WHERE strpos(bucket,:prefix)=1",prefix=operation+':').scalar_one()
  self.assertEqual(keys,1)
try:
 result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CallBudgetTests))
finally:
 server.should_exit=True;thread.join(5)
 with engine.begin() as db:
  identity.query(db,"UPDATE staging.voice_intents SET state='cancelled',finished_at=clock_timestamp() WHERE account_sid=:account AND state='reserved' AND consumed_at IS NULL",account=profile.account_sid)
  identity.query(db,"DELETE FROM staging.identity_rate_limits WHERE bucket IN ('voice-global','dialer-global','global')")
 engine.dispose()
raise SystemExit(0 if result.wasSuccessful() else 1)
