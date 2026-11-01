"""Real HTTP/PG concurrency and permissions; no live inbound route or Twilio call."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import json,os,threading,time
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from uuid import UUID,uuid4
import uvicorn
from sqlalchemy.exc import DBAPIError
from app.main import app
from app.database import make_engine
from app.identity.service import query
from app.identity.security import COOKIE,CSRF_COOKIE,digest,new_token
from app.telephony import inbound_service as service

assert os.environ['DB_HOST']=='db' and os.environ.get('DB_DEPLOYMENT','local')=='local'
assert os.environ['COMMUNICATIONS_MODE']=='disabled'
engine=make_engine()
with engine.connect() as db:
    assert query(db,"SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one()=='synthetic_only'
server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=18002,log_level='critical',access_log=False))
thread=threading.Thread(target=server.run,daemon=True);thread.start()
for _ in range(200):
    if server.started:break
    time.sleep(.025)
assert server.started

class Browser:
    def __init__(self,role='admin'):
        self.id=uuid4();self.token=new_token();self.csrf=new_token()
        with engine.begin() as db:
            query(db,'''INSERT INTO staging.identity_users(id,email,display_name,role,password_hash,mfa_secret)
                VALUES (:id,:email,:name,:role,'unused',:mfa)''',id=self.id,email=str(self.id)+'@example.invalid',name='Réception '+str(self.id)[:6],role=role,mfa=app.state.identity_cipher.encrypt(b'JBSWY3DPEHPK3PXP').decode() if role=='admin' else None)
            query(db,'''INSERT INTO staging.identity_sessions(token_hash,csrf_hash,user_id,mfa_verified,expires_at)
                VALUES (:token,:csrf,:id,true,now()+interval '1 hour')''',token=digest(self.token),csrf=digest(self.csrf),id=self.id)
    def request(self,method,path,body=None,expected=200,headers=None):
        values={'Origin':os.environ['APP_ORIGIN'],'Content-Type':'application/json','Cookie':COOKIE+'='+self.token+'; '+CSRF_COOKIE+'='+self.csrf,'X-CSRF-Token':self.csrf,**(headers or {})}
        req=Request('http://127.0.0.1:18002/api/inbound'+path,method=method,headers=values,data=json.dumps(body).encode() if body is not None else None)
        try:r=urlopen(req,timeout=15)
        except HTTPError as e:r=e
        with r:
            data=json.load(r);assert r.status==expected,(method,path,r.status,expected,data);return data

def unused_number(table, column):
    with engine.connect() as db:
        for n in range(5000,10000):
            number='+1604555'+str(n)
            if not query(db,'SELECT 1 FROM staging.'+table+' WHERE '+column+'=:phone',phone=number).first():return number
    raise AssertionError('Synthetic numbers exhausted')

try:
    admin=Browser();admin2=Browser();a=Browser('agent');b=Browser('agent')
    config=dict(name='Réception '+uuid4().hex[:8],phone=unused_number('inbound_queues','phone'),timezone='America/Toronto',hours=[dict(weekday=0,start=540,end=1020)],max_wait_seconds=60,offer_seconds=20,is_active=True,agents=[dict(user_id=str(a.id),mode='mixed')])
    queue=uuid4();Q='/queues/'+str(queue)
    a.request('POST','/queues',{**config,'id':str(queue)},403)
    admin.request('POST','/queues',{**config,'hours':[dict(weekday=0,start=600,end=500)],'id':str(queue)},422)
    admin.request('POST','/queues',{**config,'id':str(queue)},403,headers={'X-CSRF-Token':'wrong'})
    admin.request('POST','/queues',{**config,'id':str(queue)},403,headers={'Origin':'https://untrusted.example.invalid'})
    created=admin.request('POST','/queues',{**config,'id':str(queue)},201)
    assert admin.request('POST','/queues',{**config,'id':str(queue)},201)==created
    admin.request('POST','/queues',{**config,'id':str(uuid4())},409)
    assert admin.request('GET',Q)['routing_active'] is False
    assert [r['id'] for r in a.request('GET','/queues')['items']]==[str(queue)]
    b.request('GET',Q+'/board',expected=403)
    a.request('GET','/agents',expected=403)
    a.request('PATCH',Q,{**config,'version':0,'request_id':str(uuid4())},403)
    config['agents'].append(dict(user_id=str(b.id),mode='mixed'))
    update={**config,'version':0,'request_id':str(uuid4())}
    assert admin.request('PATCH',Q,update)['version']==1
    assert admin.request('PATCH',Q,update)['version']==1
    admin.request('PATCH',Q,{**update,'name':'Changed payload'},409)
    admin.request('PATCH',Q,{**update,'request_id':str(uuid4())},409)
    # Both administrators read version 1; one wins and one sees a real conflict.
    def configure(args):
        browser,name=args
        return browser.request('PATCH',Q,{**config,'name':name,'version':1,'request_id':str(uuid4())},expected=200 if browser is admin else 409)
    # Force one successful revision, then exercise a stale independent actor.
    configure((admin,config['name']+' A'));configure((admin2,config['name']+' B'))
    now=datetime.now(timezone.utc)-timedelta(minutes=2)
    phone=unused_number('contacts','phone');contact=uuid4()
    with engine.begin() as db:
        query(db,"INSERT INTO staging.contacts(id,phone,profile) VALUES (:id,:phone,'{\"display_name\":\"Client réception\"}') ON CONFLICT(phone) DO NOTHING",id=contact,phone=phone)
        contact=query(db,'SELECT id FROM staging.contacts WHERE phone=:phone',phone=phone).scalar_one()
        baseline=query(db,'SELECT row_to_json(c)::text FROM staging.contacts c WHERE id=:id',id=contact).scalar_one()
    def received(call=None,caller=phone,outcome='missed'):
        values=dict(queue_id=queue,account_sid='AC'+'a'*32,call_sid=call or 'CA'+uuid4().hex,caller_number=caller,called_number=config['phone'],outcome=outcome,received_at=now,ended_at=now+timedelta(seconds=30))
        with engine.begin() as db:return service.record_missed(db,**values)
    call='CA'+uuid4().hex
    with ThreadPoolExecutor(max_workers=2) as workers: ids=list(workers.map(lambda _:received(call),range(2)))
    assert ids[0]==ids[1];followup=ids[0];F='/followups/'+str(followup)
    with ThreadPoolExecutor(max_workers=2) as workers:assert set(workers.map(lambda _:received(),range(20)))=={followup}
    for _ in range(35): received()
    first_page=admin.request('GET',F+'/calls')
    assert len(first_page['items'])==50 and first_page['has_more']
    last_page=admin.request('GET',F+'/calls?before='+first_page['items'][-1]['id'])
    assert len(last_page['items'])==6 and not last_page['has_more']
    history=admin.request('GET',F)
    assert len(history['events'])==50 and history['has_more']
    assert admin.request('GET',F+'?before='+history['events'][-1]['id'])['events']
    try:received(call,outcome='abandoned')
    except ValueError:pass
    else:raise AssertionError('Conflicting terminal call silently overwritten')
    anonymous=[received(caller=None),received(caller=None)];assert anonymous[0]!=anonymous[1]
    row=a.request('GET',F)['followup'];assert row['contact_id']==str(contact) and row['call_count']==56
    with engine.connect() as db:assert query(db,'SELECT row_to_json(c)::text FROM staging.contacts c WHERE id=:id',id=contact).scalar_one()==baseline
    # Independent agents race from the same card version; only one can own it.
    # Coordinate the two requests, accepting either winner rather than ordering them.
    def racing(browser):
        req=Request('http://127.0.0.1:18002/api/inbound'+F,method='POST',headers={'Origin':os.environ['APP_ORIGIN'],'Content-Type':'application/json','Cookie':COOKIE+'='+browser.token+'; '+CSRF_COOKIE+'='+browser.csrf,'X-CSRF-Token':browser.csrf},data=json.dumps(dict(version=row['version'],stage='claimed',request_id=str(uuid4()))).encode())
        try:r=urlopen(req,timeout=15)
        except HTTPError as e:r=e
        with r:return r.status
    with ThreadPoolExecutor(max_workers=2) as workers:assert sorted(workers.map(racing,[a,b]))==[200,409]
    row=admin.request('GET',F)['followup'];owner=a if row['owner_id']==str(a.id) else b;other=b if owner is a else a
    other.request('POST',F,dict(version=row['version'],stage='handled',request_id=str(uuid4())),403)
    current=admin.request('GET',Q)
    admin.request('PATCH',Q,{**config,'agents':[m for m in config['agents'] if m['user_id']!=str(owner.id)],'version':current['version'],'request_id':str(uuid4())},409)
    note=dict(id=str(uuid4()),content='Note partagée, sans déclencher de rappel.')
    other.request('POST',F+'/notes',note,201);other.request('POST',F+'/notes',note,201)
    assert sum(e['action']=='note.added' for e in admin.request('GET',F)['events'])==1
    # Schedule belongs to its owner and uses the real DST resolver.
    schedule=dict(version=row['version'],stage='callback',request_id=str(uuid4()),local_start='2030-11-03T01:30',timezone='America/Toronto')
    owner.request('POST',F,schedule,422)
    result=owner.request('POST',F,{**schedule,'utc_offset_minutes':-300})
    assert owner.request('POST',F,{**schedule,'utc_offset_minutes':-300})==result
    row=admin.request('GET',F)['followup'];assert row['callback_at'].startswith('2030-11-03T06:30:00')
    owner.request('POST',F,dict(version=row['version'],stage='handled',request_id=str(uuid4())))
    next_id=received();assert next_id!=followup
    assert admin.request('GET',F)['followup']['stage']=='handled'
    row=admin.request('GET','/followups/'+str(anonymous[0]))['followup']
    owner.request('POST','/followups/'+str(anonymous[0]),{**schedule,'request_id':str(uuid4()),'version':row['version'],'utc_offset_minutes':-300},409)
    late_phone=unused_number('contacts','phone')
    late_id=received(caller=late_phone)
    assert admin.request('GET','/followups/'+str(late_id))['followup']['contact_id'] is None
    with engine.begin() as db:
        query(db,"INSERT INTO staging.contacts(id,phone,profile,do_not_contact) VALUES (:id,:phone,'{}',true) ON CONFLICT(phone) DO UPDATE SET do_not_contact=true",id=uuid4(),phone=late_phone)
    late=owner.request('GET','/followups/'+str(late_id))['followup'];assert late['do_not_contact']
    owner.request('POST','/followups/'+str(late_id),{**schedule,'request_id':str(uuid4()),'version':late['version'],'utc_offset_minutes':-300},409)
    assert received(caller=late_phone)==late_id
    assert admin.request('GET','/followups/'+str(late_id))['followup']['contact_id'] is not None
    current=admin.request('GET',Q);admin.request('PATCH',Q,{**config,'phone':'+15145550102','version':current['version'],'request_id':str(uuid4())},409)
    current=admin.request('GET',Q)
    admin.request('PATCH',Q,{**config,'is_active':False,'version':current['version'],'request_id':str(uuid4())})
    assert received()==next_id  # Late verified calls survive configuration archival.
    board=owner.request('GET',Q+'/board');assert len(board['columns'])==4 and not board['queue']['is_active']
    # A rollback after adapter failure cannot leave an orphan interaction/card.
    sid='CA'+uuid4().hex
    try:
        with engine.begin() as db:
            service.record_missed(db,queue_id=queue,account_sid='AC'+'a'*32,call_sid=sid,caller_number=None,called_number=config['phone'],outcome='missed',received_at=now,ended_at=now)
            raise RuntimeError('synthetic transaction failure')
    except RuntimeError:pass
    with engine.connect() as db:assert query(db,'SELECT count(*) FROM staging.inbound_interactions WHERE call_sid=:sid',sid=sid).scalar_one()==0
    for statement in ['UPDATE staging.inbound_interactions SET outcome=outcome','DELETE FROM staging.inbound_followup_events','DELETE FROM staging.inbound_queues']:
        try:
            with engine.begin() as db:query(db,statement)
        except DBAPIError as e:assert getattr(e.orig,'sqlstate',None)=='42501'
        else:raise AssertionError('Runtime history deletion/update was permitted')
    assert app.state.voice_calling_enabled is False
    print('Inbound HTTP/PG: admin settings, atomic ownership, idempotent terminal calls, anonymous separation, manual DST callbacks, immutable history and preserved contacts: PASS')
finally:
    server.should_exit=True;thread.join(timeout=10);engine.dispose()
