"""Real HTTP/PostgreSQL/XLSX proof with synthetic history; no provider traffic."""
import json,os,threading,time,urllib.request,urllib.error
from datetime import datetime,timedelta,timezone
from io import BytesIO
from uuid import uuid4
import uvicorn
from openpyxl import load_workbook
from app.database import make_engine
from app.identity.service import query
from app.identity.security import COOKIE,CSRF_COOKIE,new_token,digest
from app.main import app

assert os.environ['DB_HOST']=='db' and os.environ.get('DB_DEPLOYMENT','local')=='local'
assert os.environ['COMMUNICATIONS_MODE']=='disabled'
engine=make_engine()
with engine.connect() as db:assert query(db,"SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one()=='synthetic_only'
server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=18013,log_level='critical',access_log=False))
thread=threading.Thread(target=server.run,daemon=True);thread.start()
for _ in range(200):
    if server.started:break
    time.sleep(.025)
assert server.started
base='http://127.0.0.1:18013';origin=os.environ['APP_ORIGIN']
class Browser:
    def __init__(self,role='agent',verified=True):
        self.id=uuid4();self.token=new_token();self.csrf=new_token()
        with engine.begin() as db:
            query(db,'''INSERT INTO staging.identity_users(id,email,display_name,role,password_hash,mfa_secret)
                VALUES (:id,:email,:name,:role,'unused',:mfa)''',id=self.id,email=str(self.id)+'@example.invalid',name='=Agent '+str(self.id)[:6],role=role,
                mfa=app.state.identity_cipher.encrypt(b'JBSWY3DPEHPK3PXP').decode() if role=='admin' else None)
            query(db,'''INSERT INTO staging.identity_sessions(token_hash,csrf_hash,user_id,mfa_verified,expires_at)
                VALUES (:token,:csrf,:id,:verified,clock_timestamp()+interval '1 hour')''',token=digest(self.token),csrf=digest(self.csrf),id=self.id,verified=verified)
    def request(self,method,path,body=None,expected=200,raw=False,headers=None):
        settings={'Cookie':COOKIE+'='+self.token+'; '+CSRF_COOKIE+'='+self.csrf,'X-CSRF-Token':self.csrf,'Origin':origin,'Content-Type':'application/json'}
        settings.update(headers or {})
        request=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=settings,method=method)
        try:response=urllib.request.urlopen(request,timeout=25)
        except urllib.error.HTTPError as error:response=error
        with response:
            content=response.read();assert response.status==expected,(response.status,expected,content[:300])
            assert response.headers['Cache-Control']=='no-store'
            return content if raw else json.loads(content)
try:
    admin=Browser('admin');a=Browser();b=Browser();offline=Browser();unverified=Browser('admin',False)
    params='start=2026-11-01&end=2026-11-02&timezone=America%2FToronto'
    for path in ('/api/reporting/live','/api/reporting/report?'+params,'/api/reporting/export.xlsx?'+params):
        a.request('GET',path,expected=403);unverified.request('GET',path,expected=403)
    a.request('POST','/api/reporting/presence',{},headers={'Origin':'https://untrusted.invalid'},expected=403)
    a.request('POST','/api/reporting/presence',{},headers={'X-CSRF-Token':'wrong'},expected=403)
    a.request('POST','/api/reporting/presence',{})
    campaign=admin.request('POST','/api/campaigns',{'name':'Reporting '+uuid4().hex},expected=201)
    contact=uuid4();phone='+1514'+str(1000000+uuid4().int%8000000)
    with engine.begin() as db:
        query(db,"INSERT INTO staging.contacts(id,phone,profile) VALUES (:id,:phone,'{}')",id=contact,phone=phone)
    admin.request('POST','/api/campaigns/'+campaign['id']+'/contacts',dict(request_id=str(uuid4()),contact_ids=[str(contact)]))
    identifiers=[]
    specs=[(a,'2026-11-01T05:10:00+00:00','completed',120),(a,'2026-11-01T06:15:00+00:00','no-answer',None),
           (a,'2026-11-02T12:00:00+00:00','completed',60),(b,'2026-11-02T14:00:00+00:00',None,None),
           (b,'2026-11-01T08:00:00+00:00','no-answer',None)]
    with engine.begin() as db:
        for index,(agent,at,outcome,seconds) in enumerate(specs):
            identifier=uuid4();identifiers.append(identifier);parent='CA'+uuid4().hex
            stamp=datetime.fromisoformat(at);destination=phone if index in (0,1,4) else '+1514'+str(1000000+uuid4().int%8000000)
            query(db,'''INSERT INTO staging.voice_intents(id,actor_id,session_hash,profile_hash,account_sid,application_sid,
                caller_number,destination,state,parent_call_sid,created_at,expires_at,consumed_at,finished_at,outcome)
                VALUES (:id,:actor,:session,:profile,:account,:application,'+14165550100',:destination,:state,:parent,
                :created,:expires,:consumed,:finished,:outcome)''',id=identifier,actor=agent.id,session=digest(agent.token),profile='b'*64,
                account='AC'+'a'*32,application='AP'+'d'*32,destination=destination,state='finished' if outcome else 'answered',parent=parent,
                created=stamp-timedelta(seconds=2),expires=stamp+timedelta(minutes=2),consumed=stamp,finished=stamp+timedelta(seconds=seconds or 15) if outcome else None,outcome=outcome)
            if seconds is not None:
                query(db,'''INSERT INTO staging.voice_recordings(sid,intent_id,call_sid,duration,channels)
                    VALUES (:sid,:id,:call,:duration,2)''',sid='RE'+uuid4().hex,id=identifier,call=parent,duration=100 if index==0 else seconds)
            if index==0:
                query(db,"INSERT INTO staging.voice_events(intent_id,kind,fingerprint,details) VALUES (:id,'status',:hash,CAST(:details AS jsonb))",
                    id=identifier,hash=uuid4().hex*2,details=json.dumps(dict(status='completed',duration_seconds=120)))
        for status in ('reserved','cancelled'):
            query(db,'''INSERT INTO staging.voice_intents(id,actor_id,session_hash,profile_hash,account_sid,application_sid,
                caller_number,destination,state,created_at,expires_at)
                VALUES (:id,:actor,:session,:profile,:account,:application,'+14165550100',:destination,:state,
                    '2026-11-01T07:00:00Z','2026-11-01T07:02:00Z')''',id=uuid4(),actor=a.id,session=digest(a.token),profile='b'*64,account='AC'+'a'*32,application='AP'+'d'*32,destination=phone,state=status)
        for day,status in [(1,'booked'),(2,'cancelled')]:
            query(db,'''INSERT INTO staging.appointments(id,campaign_id,contact_id,created_by,request_hash,starts_at,ends_at,timezone,status,created_at)
                VALUES (:id,:campaign,:contact,:actor,:hash,'2026-11-10T15:00:00Z','2026-11-10T15:30:00Z','America/Toronto',:status,:created)''',
                id=uuid4(),campaign=campaign['id'],contact=contact,actor=a.id,hash=uuid4().hex,status=status,created=datetime(2026,11,day,15,tzinfo=timezone.utc))
        for day,action in [(1,'dialer.pause'),(1,'dialer.start'),(2,'dialer.stop'),(2,'dialer.pause_automatic')]:
            query(db,"INSERT INTO staging.identity_audit(actor_id,action,created_at) VALUES (:id,:action,:at)",id=a.id,action=action,at=datetime(2026,11,day,16,tzinfo=timezone.utc))
        query(db,"UPDATE staging.identity_sessions SET last_seen_at=clock_timestamp()-interval '10 minutes' WHERE user_id=:id",id=offline.id)
        query(db,'''INSERT INTO staging.voice_dialer_sessions(actor_id,session_hash,browser_id,campaign_id,mode,lease_until)
            VALUES (:id,:session,:browser,:campaign,'paused',clock_timestamp()+interval '90 seconds')''',id=a.id,session=digest(a.token),browser=uuid4(),campaign=campaign['id'])
    report=admin.request('GET','/api/reporting/report?'+params+'&agent_id='+str(a.id))
    m=report['totals'];assert (m['calls'],m['answered'],m['contacts'],m['bookings'],m['cancelled_bookings'])==(3,2,2,2,1),m
    assert (m['pauses'],m['stops'],m['automatic_pauses'],m['talk_seconds'],m['duration_known'],m['average_talk_seconds'])==(1,1,1,180,2,90),m
    assert len(report['daily'])==2 and [row['calls'] for row in report['daily']]==[2,1]
    whole=admin.request('GET','/api/reporting/report?'+params)
    assert whole['totals']['contacts']<sum(agent['metrics']['contacts'] for agent in whole['agents'])
    assert len(report['hourly'])==49
    repeated=[row for row in report['hourly'] if row['date']=='2026-11-01' and row['label']=='01:00']
    assert len(repeated)==2 and {row['utc_offset'] for row in repeated}=={'-0400','-0500'} and [row['calls'] for row in repeated]==[1,1]
    zero=admin.request('GET','/api/reporting/report?'+params+'&agent_id='+str(offline.id))
    assert zero['totals']['calls']==0 and len(zero['daily'])==2 and zero['totals']['average_talk_seconds'] is None
    live=admin.request('GET','/api/reporting/live');state={row['id']:row for row in live['items']}
    assert state[str(a.id)]['status']=='paused' and state[str(a.id)]['online'] is True
    assert state[str(b.id)]['status']=='connected' and state[str(offline.id)]['status']=='offline'
    a.request('POST','/api/reporting/presence',{})
    for suffix in ('start=2026-01-01&end=2026-05-01','start=2026-01-01&end=2026-01-02&timezone=invalid','start=9999-01-01&end=9999-01-02'):
        admin.request('GET','/api/reporting/report?'+suffix,expected=422)
    admin.request('GET','/api/reporting/report?'+params+'&agent_id='+str(uuid4()),expected=404)
    content=admin.request('GET','/api/reporting/export.xlsx?'+params+'&agent_id='+str(a.id),raw=True)
    book=load_workbook(BytesIO(content),read_only=True)
    assert book.sheetnames==['Synthèse','Par jour','Par heure','Repères']
    rows=list(book['Synthèse'].rows);assert rows[1][0].data_type=='s' and rows[1][2].value==3
    assert len(list(book['Par heure'].rows))==50
    from app.reporting.routes import export_slots
    assert export_slots.acquire(blocking=False)
    try:
        admin.request('GET','/api/reporting/export.xlsx?'+params,expected=429)
        a.request('GET','/api/reporting/export.xlsx?'+params,expected=403)
    finally:export_slots.release()
    assert admin.request('GET','/api/reporting/export.xlsx?'+params+'&agent_id='+str(a.id),raw=True)[:2]==b'PK'
    # A long report must not retain the actor lock needed by calling actions,
    # and revocation while calculating must prevent delivery of the report.
    from concurrent.futures import ThreadPoolExecutor
    from app.reporting import routes as reporting_routes
    original_report=reporting_routes.service.report
    entered=threading.Event();release=threading.Event()
    def slow_report(*args,**kwargs):
        result=original_report(*args,**kwargs);entered.set()
        assert release.wait(15)
        return result
    reporting_routes.service.report=slow_report
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(lambda:admin.request('GET','/api/reporting/report?'+params,expected=403))
            assert entered.wait(10)
            try:
                admin.request('POST','/api/reporting/presence',{})
                with engine.begin() as db:query(db,"UPDATE staging.identity_users SET role='agent' WHERE id=:id",id=admin.id)
            finally:release.set()
            future.result(timeout=15)
    finally:
        reporting_routes.service.report=original_report
        with engine.begin() as db:query(db,"UPDATE staging.identity_users SET role='admin' WHERE id=:id",id=admin.id)
    print('Reporting HTTP/PG/XLSX: admin-only access, CSRF, measured presence, reservations excluded, distinct contacts, daily/hourly/DST, bookings, pauses, known durations, zero days and private typed exports: PASS')
finally:
    server.should_exit=True;thread.join(5);engine.dispose()
