"""Real HTTP/PG checks for shared-calendar authorization, concurrency and DST."""
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

from urllib.parse import urlencode

anonymous=Browser();anonymous.request('GET','/api/calendar?start=2026-01-01T00:00:00Z&end=2026-01-02T00:00:00Z',expected=401)
a=admin.request('POST','/api/campaigns',dict(name='Calendrier '+uuid.uuid4().hex),expected=201)
A='/api/campaigns/'+a['id']
agent_a,id_a=agent();agent_b,id_b=agent()
admin.request('PUT',A+'/agents/'+id_a,dict(is_active=True))
contact=code('''identifier=uuid.uuid4()
with make_engine().begin() as db:
    for number in range(200,250):
        inserted=query(db,"INSERT INTO staging.contacts(id,phone,profile) VALUES (:id,:phone,CAST(:profile AS jsonb)) ON CONFLICT(phone) DO NOTHING RETURNING id",id=identifier,phone='+1604555'+str(number).zfill(4),profile=json.dumps({'display_name':'Calendrier synthétique'})).first()
        if inserted:break
    else:raise AssertionError('Synthetic phone fixtures exhausted')
print(json.dumps(str(identifier)))
''')
admin.request('POST',A+'/contacts',dict(request_id=str(uuid.uuid4()),contact_ids=[contact]))
body=dict(id=str(uuid.uuid4()),campaign_id=a['id'],contact_id=contact,membership_version=0,local_start='2026-11-01T01:30',timezone='America/Toronto',duration_minutes=30,notes='Premier RDV')
agent_b.request('POST','/api/calendar',body,expected=403)
agent_a.request('POST','/api/calendar',body,expected=422) # DST overlap needs explicit offset
body['utc_offset_minutes']=-300
agent_a.request('POST','/api/calendar',{**body,'created_by':id_b},expected=422)
booked=agent_a.request('POST','/api/calendar',body,expected=201)
assert booked['starts_at'].startswith('2026-11-01T06:30')
assert agent_a.request('POST','/api/calendar',body,expected=201)['id']==booked['id']
agent_a.request('POST','/api/calendar',{**body,'notes':'Different retry'},expected=409)
path='/api/calendar/'+booked['id']
assert agent_b.request('GET',path)['can_edit'] is False
assert agent_a.request('GET',path)['can_edit'] is True
assert admin.request('GET',path)['can_edit'] is True
stage=next(s for s in admin.request('GET',A+'/board')['stages'] if s['kind']=='appointment')
assert stage['total']==1
patch={k:v for k,v in body.items() if k not in ['id','campaign_id','contact_id','membership_version']}
patch.update(version=0,status='booked',notes='Notes modifiées')
agent_a.request('PATCH',path,{**patch,'contact_id':str(uuid.uuid4())},expected=422)
agent_b.request('PATCH',path,patch,expected=403)
assert agent_a.request('PATCH',path,patch)['version']==1
agent_a.request('PATCH',path,patch,expected=409)
# Overlapping meetings are allowed, with distinct ids and the current membership version.
version=admin.request('GET',A+'/contacts/'+contact)['contact']['version']
second=agent_a.request('POST','/api/calendar',{**body,'id':str(uuid.uuid4()),'membership_version':version},expected=201)
# The shared calendar exposes the appointment, not the source campaign board.
agent_b.request('GET',A+'/board',expected=403)
params=urlencode(dict(start='2026-11-01T00:00:00Z',end='2026-11-02T00:00:00Z'))
assert booked['id'] in [r['id'] for r in agent_b.request('GET','/api/calendar?'+params)['items']]
agent_a.request('GET','/api/calendar?'+urlencode(dict(start='2026-01-01T00:00:00Z',end='2027-01-01T00:00:00Z')),expected=422)
# Two editors reading the same version cannot silently overwrite one another.
patch['version']=1
with ThreadPoolExecutor(max_workers=2) as pool:
    def race(notes):
        try:
            agent_a.request('PATCH',path,{**patch,'notes':notes})
            return 200
        except AssertionError as error:
            assert 409 in error.args[0]
            return 409
    assert sorted(pool.map(race,['Concurrent A','Concurrent B']))==[200,409]
# Cancellation preserves history and does not reverse another meeting's pipeline stage.
current=admin.request('GET',path)['appointment']
cancel=admin.request('PATCH',path,{**patch,'version':current['version'],'status':'cancelled'})
assert cancel['status']=='cancelled'
assert len(admin.request('GET',path)['events'])==4
assert admin.request('GET',A+'/contacts/'+contact)['contact']['stage_id']==stage['id']
# Reassignment revocation blocks creation while retaining creator ownership on existing meetings.
admin.request('PUT',A+'/agents/'+id_a,dict(is_active=False))
agent_a.request('POST','/api/calendar',{**body,'id':str(uuid.uuid4()),'membership_version':version},expected=403)
assert agent_a.request('PATCH',path,{**patch,'version':cancel['version'],'status':'no_show'})['status']=='no_show'
# DST gaps and invalid zones must fail before writes.
admin.request('POST','/api/calendar',{**body,'id':str(uuid.uuid4()),'local_start':'2026-03-08T02:30','utc_offset_minutes':None},expected=422)
admin.request('POST','/api/calendar',{**body,'id':str(uuid.uuid4()),'timezone':'Invalid/Zone'},expected=422)
admin.request('POST','/api/calendar',{**body,'id':str(uuid.uuid4()),'membership_version':0},expected=409)
# Runtime role cannot rewrite/delete the appointment audit or delete meetings.
code('''from sqlalchemy.exc import DBAPIError
engine=make_engine()
for statement in ['DELETE FROM staging.appointments','UPDATE staging.appointment_events SET action=action','DELETE FROM staging.appointment_events','TRUNCATE staging.appointment_events']:
    try:
        with engine.begin() as db:query(db,statement)
    except DBAPIError as error:
        assert error.orig.sqlstate=='42501'
    else:raise AssertionError('Appointment history permissions are too broad')
print(json.dumps(True))
''')
# Bounded listing and event cursors must not silently lose rows.
code("""with make_engine().begin() as db:
    query(db,\"\"\"INSERT INTO staging.appointments(id,campaign_id,contact_id,created_by,request_hash,starts_at,ends_at,timezone)
        SELECT gen_random_uuid(),CAST(:campaign AS uuid),CAST(:contact AS uuid),CAST(:actor AS uuid),'pagination-fixture',
        '2026-12-01T10:00:00Z'::timestamptz,'2026-12-01T10:30:00Z'::timestamptz,'America/Toronto'
        FROM generate_series(1,105)\"\"\",**payload)
print(json.dumps(True))
""",dict(campaign=a['id'],contact=contact,actor=id_a))
period=urlencode(dict(start='2026-12-01T00:00:00Z',end='2026-12-02T00:00:00Z',creator=id_a))
code("""with make_engine().begin() as db:
    for end in ['2026-12-01T00:00:00Z','2026-12-01T00:30:00Z']:
        query(db,\"\"\"INSERT INTO staging.appointments(id,campaign_id,contact_id,created_by,request_hash,starts_at,ends_at,timezone)
            VALUES (gen_random_uuid(),:campaign,:contact,:actor,'boundary-fixture','2026-11-30T23:30:00Z',CAST(:end AS timestamptz),'America/Toronto')\"\"\",end=end,**payload)
print(json.dumps(True))
""",dict(campaign=a['id'],contact=contact,actor=id_a))
first=agent_b.request('GET','/api/calendar?'+period)
last=agent_b.request('GET','/api/calendar?'+period+'&offset=100')
assert len(first['items'])==100 and first['has_more']
assert len(last['items'])==6 and not last['has_more']
assert len({r['id'] for r in first['items']+last['items']})==106
assert not agent_b.request('GET','/api/calendar?'+period+'&status=cancelled')['items']
code("""with make_engine().begin() as db:
    query(db,\"\"\"INSERT INTO staging.appointment_events(appointment_id,actor_id,action,details)
        SELECT a.id,a.created_by,'appointment.updated',jsonb_build_object('after',jsonb_build_object('starts_at',a.starts_at,'ends_at',a.ends_at,'timezone',a.timezone,'notes',a.notes,'status',a.status))
        FROM staging.appointments a CROSS JOIN generate_series(1,53) WHERE a.id=:id\"\"\",id=payload)
print(json.dumps(True))
""",booked['id'])
first=agent_b.request('GET',path)
last=agent_b.request('GET',path+'?before='+first['events'][-1]['id'])
assert len(first['events'])==50 and first['has_more']
assert last['events'] and not last['has_more']
assert not {e['id'] for e in first['events']} & {e['id'] for e in last['events']}
print('Shared calendar: permissions, DST, atomic pipeline booking, overlap, idempotency, concurrent edits, cancellation and immutable history: PASS')
