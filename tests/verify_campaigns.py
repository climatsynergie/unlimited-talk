"""Real HTTP/PG checks for campaign authorization, concurrency and global flags."""
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
    if result.returncode:raise AssertionError('Campaign fixture/database verification failed: '+result.stderr[-1000:])
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
anonymous=Browser();anonymous.request('GET','/api/campaigns',expected=401)
prefix='Campagne '+uuid.uuid4().hex[:8]
a=admin.request('POST','/api/campaigns',dict(name=prefix+' A'),expected=201)
b=admin.request('POST','/api/campaigns',dict(name=prefix+' B'),expected=201)
A='/api/campaigns/'+a['id'];B='/api/campaigns/'+b['id']
admin.request('POST','/api/campaigns',dict(name=(prefix+' A').upper()),expected=409)
admin.request('POST','/api/campaigns',dict(name='Bad zone',timezone='Invalid/Timezone'),expected=422)


def agent():
    invitation=admin.request('POST','/api/admin/invitations',dict(email='campaign-agent-'+uuid.uuid4().hex+'@example.invalid',display_name='Agent campagne',role='agent'),expected=201)
    browser=Browser();result=browser.request('POST','/api/auth/invitations/accept',dict(token=invitation['token'],password='Campaign integration password 2026!'))
    return browser,result['user']['id']

agent_a,id_a=agent();agent_b,id_b=agent()
assert agent_a.request('GET','/api/campaigns')['items']==[]
agent_a.request('GET',A+'/board',expected=403)
agent_a.request('POST','/api/campaigns',dict(name='Forbidden'),expected=403)
admin.request('PUT',A+'/agents/'+id_a,dict(is_active=True));admin.request('PUT',B+'/agents/'+id_b,dict(is_active=True))
assert [c['id'] for c in agent_a.request('GET','/api/campaigns')['items']]==[a['id']]
agent_a.request('GET',B+'/board',expected=403)
contact=code('''identifier=uuid.uuid4()
with make_engine().begin() as db:
    for number in range(150,200):
        phone='+1604555'+str(number).zfill(4)
        inserted=query(db,"INSERT INTO staging.contacts(id,phone,profile) VALUES (:id,:phone,CAST(:profile AS jsonb)) ON CONFLICT(phone) DO NOTHING RETURNING id",id=identifier,phone=phone,profile=json.dumps({'display_name':'Test campagnes'})).first()
        if inserted:break
    else:raise AssertionError('Synthetic phone fixtures exhausted')
print(json.dumps(str(identifier)))
''')
enrollment=dict(request_id=str(uuid.uuid4()),contact_ids=[contact])
assert admin.request('POST',A+'/contacts',enrollment)['added']==1
assert admin.request('POST',A+'/contacts',enrollment)['added']==1
assert admin.request('POST',A+'/contacts',{**enrollment,'request_id':str(uuid.uuid4())})['existing']==1
assert admin.request('POST',B+'/contacts',dict(request_id=str(uuid.uuid4()),contact_ids=[contact]))['added']==1
source_jobs=admin.request('GET','/api/imports')['items']
source=next(j for j in source_jobs if j['status']=='completed')
assert admin.request('POST',A+'/contacts',dict(request_id=str(uuid.uuid4()),import_id=source['id']))['total']>0


def stage(path,kind):return next(s for s in admin.request('GET',path+'/board')['stages'] if s['kind']==kind)
def card(browser,path):return browser.request('GET',path+'/contacts/'+contact)['contact']
def move(browser,path,destination,version,expected=200,request_id=None):
    return browser.request('POST',path+'/contacts/'+contact+'/move',dict(request_id=request_id or str(uuid.uuid4()),stage_id=destination,version=version),expected)

custom=admin.request('POST',A+'/stages',dict(name='À vérifier',color='blue'),expected=201)['id']
admin.request('PATCH',A+'/stages/'+custom,dict(name='À revoir',color='green'))
admin.request('POST',A+'/stages',dict(name='À REVOIR',color='blue'),expected=409)
agent_a.request('POST',A+'/stages',dict(name='Forbidden'),expected=403)
board=admin.request('GET',A+'/board');ids=[s['id'] for s in board['stages']]
admin.request('PUT',A+'/stage-order',dict(stage_ids=ids[::-1]))
admin.request('PUT',A+'/stage-order',dict(stage_ids=ids[:-1]),expected=409)
initial=card(agent_a,A);request_id=str(uuid.uuid4())
assert move(agent_a,A,custom,initial['version'],request_id=request_id)['version']==initial['version']+1
assert move(agent_a,A,custom,initial['version'],request_id=request_id)['version']==initial['version']+1
move(agent_a,A,stage(A,'new')['id'],initial['version'],expected=409)
move(agent_a,A,stage(B,'new')['id'],initial['version']+1,expected=400)
admin.request('DELETE',A+'/stages/'+custom,expected=409)
note=dict(id=str(uuid.uuid4()),content='Note partagée entre les équipes.')
agent_a.request('POST',A+'/contacts/'+contact+'/notes',note,expected=201)
agent_a.request('POST',A+'/contacts/'+contact+'/notes',note,expected=201)
assert sum(n['id']==note['id'] for n in agent_b.request('GET',B+'/contacts/'+contact)['notes'])==1
agent_a.request('GET','/api/contacts',expected=403)
for number in range(52):
    agent_a.request('POST',A+'/contacts/'+contact+'/notes',dict(id=str(uuid.uuid4()),content='Note de pagination '+str(number)),expected=201)
view=agent_b.request('GET',B+'/contacts/'+contact)
assert len(view['notes'])==50 and view['notes_has_more']
assert len(agent_b.request('GET',B+'/contacts/'+contact+'/notes?offset=50')['items'])==3
recent=agent_a.request('GET',A+'/contacts/'+contact)
assert recent['events_has_more']
assert agent_a.request('GET',A+'/contacts/'+contact+'/events?before='+recent['events'][-1]['id'])['items']

move(agent_a,A,stage(A,'non_interested')['id'],card(agent_a,A)['version'])
assert card(agent_b,B)['non_interested']
assert card(agent_b,B)['stage_id']==stage(B,'non_interested')['id']
move(agent_b,B,stage(B,'new')['id'],card(agent_b,B)['version'],expected=409)
restore=dict(request_id=str(uuid.uuid4()),do_not_contact=False,non_interested=False,confirmation='REACTIVER',expected_updated_at=card(admin,A)['contact_updated_at'])
agent_a.request('POST',A+'/contacts/'+contact+'/restore',restore,expected=403)
admin.request('POST',A+'/contacts/'+contact+'/restore',restore)
assert not card(agent_b,B)['non_interested']
move(agent_a,A,stage(A,'do_not_contact')['id'],card(agent_a,A)['version'])
assert card(agent_b,B)['do_not_contact'] and card(agent_b,B)['stage_id']==stage(B,'do_not_contact')['id']
# Soft removal keeps the global identity, notes and other campaign memberships.
before=card(admin,B)
remove=dict(request_id=str(uuid.uuid4()),version=before['version'])
admin.request('POST',B+'/contacts/'+contact+'/remove',remove)
admin.request('POST',B+'/contacts/'+contact+'/remove',remove)
agent_b.request('GET',B+'/contacts/'+contact,expected=404)
assert card(agent_a,A)['do_not_contact']
admin.request('POST',B+'/contacts',dict(request_id=str(uuid.uuid4()),contact_ids=[contact]))
assert card(agent_b,B)['do_not_contact'] and card(agent_b,B)['stage_id']==stage(B,'do_not_contact')['id']
# Two agents race from one version; only one move can commit.
admin.request('POST',A+'/contacts/'+contact+'/restore',{**restore,'request_id':str(uuid.uuid4()),'expected_updated_at':card(admin,A)['contact_updated_at']})
admin.request('PUT',A+'/agents/'+id_b,dict(is_active=True))
version=card(agent_a,A)['version']

def racing(args):
    browser,destination=args
    try:move(browser,A,destination,version);return 200
    except AssertionError as error:
        assert error.args[0][2]==409,error
        return 409

with ThreadPoolExecutor(max_workers=2) as pool:
    assert sorted(pool.map(racing,[(agent_a,stage(A,'new')['id']),(agent_b,custom)]))==[200,409]
assert card(agent_a,A)['version']==version+1
# Revocation takes effect on the next request, independent of cached client state.
admin.request('PUT',A+'/agents/'+id_b,dict(is_active=False))
agent_b.request('GET',A+'/contacts/'+contact,expected=403)
# Reordering/archiving never deletes stage history or contact identities.
if card(admin,A)['stage_id']==custom:move(admin,A,stage(A,'new')['id'],card(admin,A)['version'])
admin.request('DELETE',A+'/stages/'+custom)
admin.request('DELETE',A+'/stages/'+stage(A,'new')['id'],expected=409)
admin.request('PATCH',A,dict(name=a['name'],description='',timezone='America/Toronto',is_active=False,version=0))
agent_a.request('GET',A+'/board',expected=403)
assert admin.request('GET',A+'/board')['campaign']['is_active'] is False
admin.request('PATCH',A,dict(name=a['name'],description='',timezone='America/Toronto',is_active=True,version=1))
# Board pages retain every card while bounding the initial response.
page_contacts=code('''with make_engine().begin() as db:
    rows=query(db,"INSERT INTO staging.contacts(id,phone,profile) SELECT gen_random_uuid(),'+1780555'||lpad(n::text,4,'0'),'{\\"display_name\\":\\"Pagination\\"}'::jsonb FROM generate_series(100,125) n ON CONFLICT(phone) DO UPDATE SET profile=contacts.profile RETURNING id").scalars().all()
print(json.dumps([str(i) for i in rows]))
''')
admin.request('POST',A+'/contacts',dict(request_id=str(uuid.uuid4()),contact_ids=page_contacts[:25]))
new_stage=stage(A,'new')
assert len(new_stage['items'])==20 and new_stage['total']>=25
remaining=admin.request('GET',A+'/cards?stage_id='+new_stage['id']+'&after='+new_stage['items'][-1]['queue_position'])
assert len({r['contact_id'] for r in [*new_stage['items'],*remaining['items']]})==new_stage['total']
admin.request('POST',A+'/contacts',dict(request_id=str(uuid.uuid4()),contact_ids=[page_contacts[-1],str(uuid.uuid4())]),expected=400)
admin.request('GET',A+'/contacts/'+page_contacts[-1],expected=404)
# Notes/events must remain append-only even for runtime SQL.
code('''from sqlalchemy.exc import DBAPIError
for table in ['contact_notes','campaign_events']:
    try:
        with make_engine().begin() as db:query(db,'DELETE FROM staging.'+table)
    except DBAPIError:pass
    else:raise AssertionError('Runtime can erase history')
print('null')
''')
print('Campaign HTTP/PG: assignments, cross-campaign access, bulk enrollment, stage rules, shared notes, global restrictions, reactivation, racing versions, revocation and archive preservation: PASS')
