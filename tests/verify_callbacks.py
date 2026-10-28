"""Real HTTP/PG checks for shared-callback authorization, concurrency and DST."""
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import shlex
import subprocess
import urllib.error
import urllib.request
import uuid

root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root)]
compose+=shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'
base=os.environ.get('FOUNDATION_TEST_URL','http://127.0.0.1:8110')
origin=config['services']['api']['environment']['APP_ORIGIN']


def code(source,payload=None):
    prefix='import json,uuid,os\nfrom app.database import make_engine\nfrom app.identity.service import query\npayload=json.loads('+repr(json.dumps(payload))+')\n'
    result=subprocess.run([*compose,'exec','-T','api','python','-'],input=prefix+source,text=True,capture_output=True)
    if result.returncode:raise AssertionError('Calendar fixture/database verification failed: '+result.stderr[-1000:])
    return json.loads(result.stdout)


class Browser:
    def __init__(self):self.cookies={}
    def request(self,method,path,body=None,expected=200):
        headers={'Origin':origin,'Content-Type':'application/json','Cookie':'; '.join(k+'='+v for k,v in self.cookies.items())}
        if '__Host-ut_csrf' in self.cookies:headers['X-CSRF-Token']=self.cookies['__Host-ut_csrf']
        req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
        try:response=urllib.request.urlopen(req,timeout=30)
        except urllib.error.HTTPError as error:response=error
        with response:
            result=json.load(response)
            assert response.status==expected,(method,path,response.status,expected,result)
            for header in response.headers.get_all('Set-Cookie',[]):
                cookie=SimpleCookie();cookie.load(header)
                for key,value in cookie.items():self.cookies[key]=value.value
            return result

seed=code('''import pyotp
from app.identity.security import encryption_key,hash_password,new_token
identifier=uuid.uuid4();secret=pyotp.random_base32();password=new_token();email='campaign-admin-'+uuid.uuid4().hex+'@example.invalid'
cipher=encryption_key(os.environ['IDENTITY_KEY_FILE'])
with make_engine().begin() as db:
    query(db,"INSERT INTO staging.identity_users(id,email,display_name,role,password_hash,mfa_secret) VALUES (:id,:email,'Admin campagnes','admin',:password,:secret)",id=identifier,email=email,password=hash_password(password),secret=cipher.encrypt(secret.encode()).decode())
print(json.dumps(dict(email=email,password=password,factor=pyotp.TOTP(secret).now())))
''')
admin=Browser();admin.request('POST','/api/auth/login',seed)
def agent():
    invitation=admin.request('POST','/api/admin/invitations',dict(email='campaign-agent-'+uuid.uuid4().hex+'@example.invalid',display_name='Agent campagne',role='agent'),expected=201)
    browser=Browser();result=browser.request('POST','/api/auth/invitations/accept',dict(token=invitation['token'],password='Campaign integration password 2026!'))
    return browser,result['user']['id']

from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
future=(datetime.now(timezone.utc)+timedelta(days=3)).astimezone(ZoneInfo('America/Toronto')).replace(second=0,microsecond=0)
schedule=dict(local_start=future.replace(tzinfo=None).isoformat(),timezone='America/Toronto',utc_offset_minutes=int(future.utcoffset().total_seconds()/60),notes='Rappel demandé')
a=admin.request('POST','/api/campaigns',dict(name='Rappels '+uuid.uuid4().hex),expected=201)
b=admin.request('POST','/api/campaigns',dict(name='Autres rappels '+uuid.uuid4().hex),expected=201)
A='/api/campaigns/'+a['id'];B='/api/campaigns/'+b['id']
agent_a,id_a=agent();agent_b,id_b=agent()
admin.request('PUT',A+'/agents/'+id_a,dict(is_active=True));admin.request('PUT',B+'/agents/'+id_b,dict(is_active=True))

def contact():
    cid=code('''identifier=uuid.uuid4()
with make_engine().begin() as db:
    for number in range(100,200):
        row=query(db,"INSERT INTO staging.contacts(id,phone,profile) VALUES (:id,:phone,CAST(:profile AS jsonb)) ON CONFLICT(phone) DO NOTHING RETURNING id",id=identifier,phone='+1709555'+str(number).zfill(4),profile=json.dumps({'display_name':'Contact rappel synthétique'})).first()
        if row:break
    else:raise AssertionError('Synthetic callback fixtures exhausted')
print(json.dumps(str(identifier)))
''')
    admin.request('POST',A+'/contacts',dict(request_id=str(uuid.uuid4()),contact_ids=[cid]))
    return cid


def create(cid=None):
    cid=cid or contact()
    version=admin.request('GET',A+'/contacts/'+cid)['contact']['version']
    body=dict(**schedule,id=str(uuid.uuid4()),campaign_id=a['id'],contact_id=cid,membership_version=version)
    return agent_a.request('POST','/api/callbacks',body,expected=201),body


def due(identifier,minutes):
    code('''with make_engine().begin() as db:
    query(db,"UPDATE staging.callbacks SET due_at=clock_timestamp()-make_interval(mins=>:minutes) WHERE id=:id",id=payload['id'],minutes=payload['minutes'])
print(json.dumps(True))
''',dict(id=identifier,minutes=minutes))

anonymous=Browser();anonymous.request('GET','/api/callbacks',expected=401)
row,body=create();path='/api/callbacks/'+row['id'];cid=body['contact_id']
assert row['owner_id']==id_a and row['status']=='scheduled'
assert agent_a.request('POST','/api/callbacks',body,expected=201)['id']==row['id']
agent_a.request('POST','/api/callbacks',{**body,'notes':'Different retry'},expected=409)
agent_a.request('POST','/api/callbacks',{**body,'owner_id':id_b},expected=422)
agent_b.request('GET',path,expected=403)
assert not agent_b.request('GET','/api/callbacks')['items']
agent_b.request('GET','/api/callbacks?owner='+id_a,expected=403)
assert admin.request('GET',path)['callback']['id']==row['id']
assert not agent_a.request('GET','/api/callbacks/priority')['items']
assert next(s for s in admin.request('GET',A+'/board')['stages'] if s['kind']=='callback')['total']==1
version=admin.request('GET',A+'/contacts/'+cid)['contact']['version']
agent_a.request('POST','/api/callbacks',{**body,'id':str(uuid.uuid4()),'membership_version':version},expected=409)
admin.request('POST',B+'/contacts',dict(request_id=str(uuid.uuid4()),contact_ids=[cid]))
agent_b.request('POST','/api/callbacks',{**body,'id':str(uuid.uuid4()),'campaign_id':b['id'],'membership_version':0},expected=409)
# Two agents in different campaigns cannot acquire competing reservations.
competing=contact()
admin.request('POST',B+'/contacts',dict(request_id=str(uuid.uuid4()),contact_ids=[competing]))
with ThreadPoolExecutor(max_workers=2) as pool:
    def compete(pair):
        browser,campaign_id=pair
        attempt={**schedule,'id':str(uuid.uuid4()),'campaign_id':campaign_id,'contact_id':competing,'membership_version':0}
        try:browser.request('POST','/api/callbacks',attempt,expected=201);return 201
        except AssertionError as error:assert 409 in error.args[0];return 409
    assert sorted(pool.map(compete,[(agent_a,a['id']),(agent_b,b['id'])]))==[201,409]
patch={**schedule,'version':0,'status':'scheduled'}
agent_b.request('PATCH',path,patch,expected=403)
with ThreadPoolExecutor(max_workers=2) as pool:
    def race(notes):
        try:agent_a.request('PATCH',path,{**patch,'notes':notes});return 200
        except AssertionError as error:assert 409 in error.args[0];return 409
    assert sorted(pool.map(race,['Concurrent A','Concurrent B']))==[200,409]
agent_a.request('PATCH',path,patch,expected=409)
second,_=create();due(row['id'],15);due(second['id'],5)
priority=agent_a.request('GET','/api/callbacks/priority')['items']
assert [r['id'] for r in priority[:2]]==[row['id'],second['id']]
assert not agent_b.request('GET','/api/callbacks/priority')['items']
assert agent_a.request('GET',path)['callback']['version']==1 # priority reads never claim or mutate
admin.request('PUT',A+'/agents/'+id_a,dict(is_active=False))
assert not agent_a.request('GET','/api/callbacks/priority')['items']
assert agent_a.request('GET',path)['callback']['blocked_reason']=='unassigned'
admin.request('PUT',A+'/agents/'+id_a,dict(is_active=True))
assert agent_a.request('GET','/api/callbacks/priority')['items']
current=agent_a.request('GET',path)['callback']
# Closing an overdue callback does not need a new future date.
past=datetime.fromisoformat(current['due_at'].replace('Z','+00:00')).astimezone(ZoneInfo(current['timezone']))
closing={**patch,'local_start':past.replace(tzinfo=None,second=0,microsecond=0).isoformat(),'utc_offset_minutes':int(past.utcoffset().total_seconds()/60),'version':current['version'],'status':'completed'}
assert agent_a.request('PATCH',path,closing)['status']=='completed'
agent_a.request('PATCH',path,{**patch,'version':current['version']+1},expected=409)
assert all(r['id']!=row['id'] for r in agent_a.request('GET','/api/callbacks/priority')['items'])
# Global opt-out cancels reservations atomically, even from another campaign.
ni=next(s for s in admin.request('GET',B+'/board')['stages'] if s['kind']=='non_interested')
other,otherbody=create();othercid=otherbody['contact_id']
admin.request('POST',B+'/contacts',dict(request_id=str(uuid.uuid4()),contact_ids=[othercid]))
admin.request('POST',B+'/contacts/'+othercid+'/move',dict(request_id=str(uuid.uuid4()),stage_id=ni['id'],version=0))
assert admin.request('GET','/api/callbacks/'+other['id'])['callback']['status']=='cancelled'
assert admin.request('GET','/api/callbacks/'+other['id'])['events'][0]['details']['reason']=='non_interested'
# An appointment resolves its pending callback without deleting history.
meeting_cb,meeting_body=create();meetingcid=meeting_body['contact_id']
version=admin.request('GET',A+'/contacts/'+meetingcid)['contact']['version']
admin.request('POST','/api/calendar',{**schedule,'id':str(uuid.uuid4()),'campaign_id':a['id'],'contact_id':meetingcid,'membership_version':version,'duration_minutes':30},expected=201)
assert admin.request('GET','/api/callbacks/'+meeting_cb['id'])['callback']['status']=='cancelled'
assert admin.request('GET','/api/callbacks/'+meeting_cb['id'])['events'][0]['details']['reason']=='appointment.booked'
removed,removedbody=create();removedcid=removedbody['contact_id']
version=admin.request('GET',A+'/contacts/'+removedcid)['contact']['version']
admin.request('POST',A+'/contacts/'+removedcid+'/remove',dict(request_id=str(uuid.uuid4()),version=version))
assert admin.request('GET','/api/callbacks/'+removed['id'])['callback']['status']=='cancelled'
# Past/invalid date input, forged ownership and obsolete memberships cannot create reminders.
fresh=contact()
invalid={**schedule,'id':str(uuid.uuid4()),'campaign_id':a['id'],'contact_id':fresh,'membership_version':0}
agent_a.request('POST','/api/callbacks',{**invalid,'local_start':'2020-01-01T12:00','utc_offset_minutes':None},expected=422)
agent_a.request('POST','/api/callbacks',{**invalid,'timezone':'Invalid/Zone'},expected=422)
agent_a.request('POST','/api/callbacks',{**invalid,'membership_version':99},expected=409)
# Immutable runtime permissions are enforced by PostgreSQL.
code('''from sqlalchemy.exc import DBAPIError
for statement in ['DELETE FROM staging.callbacks','UPDATE staging.callback_events SET action=action','DELETE FROM staging.callback_events','TRUNCATE staging.callback_events']:
    try:
        with make_engine().begin() as db:query(db,statement)
    except DBAPIError as error:assert error.orig.sqlstate=='42501'
    else:raise AssertionError('Callback history permissions are too broad')
print(json.dumps(True))
''')
# Historical pagination and immutable event cursors remain usable beyond one page.
code("""with make_engine().begin() as db:
    query(db,\"\"\"INSERT INTO staging.callbacks(id,campaign_id,contact_id,owner_id,request_hash,due_at,timezone,status)
        SELECT gen_random_uuid(),CAST(:campaign AS uuid),CAST(:contact AS uuid),CAST(:owner AS uuid),'pagination-fixture',
        now()+interval '3 days','America/Toronto','completed' FROM generate_series(1,105)\"\"\",**payload)
print(json.dumps(True))
""",dict(campaign=a['id'],contact=cid,owner=id_a))
first=agent_a.request('GET','/api/callbacks?scope=history')
last=agent_a.request('GET','/api/callbacks?scope=history&offset=100')
assert len(first['items'])==100 and first['has_more']
assert last['items'] and not last['has_more']
assert not {r['id'] for r in first['items']} & {r['id'] for r in last['items']}
code("""with make_engine().begin() as db:
    query(db,\"\"\"INSERT INTO staging.callback_events(callback_id,actor_id,action,details)
        SELECT cb.id,cb.owner_id,'callback.updated',jsonb_build_object('after',jsonb_build_object('due_at',cb.due_at,'timezone',cb.timezone,'notes',cb.notes,'status',cb.status))
        FROM staging.callbacks cb CROSS JOIN generate_series(1,53) WHERE cb.id=:id\"\"\",id=payload)
print(json.dumps(True))
""",row['id'])
first=agent_a.request('GET',path)
last=agent_a.request('GET',path+'?before='+first['events'][-1]['id'])
assert len(first['events'])==50 and first['has_more']
assert last['events'] and not last['has_more']
assert not {e['id'] for e in first['events']} & {e['id'] for e in last['events']}
print('Callbacks: ownership, durable reservations, priority, opt-out/booking/removal cancellation, stale edits and immutable history: PASS')
