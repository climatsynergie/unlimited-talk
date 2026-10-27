"""Real HTTP/database authorization tests, using only disposable synthetic users."""
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import shlex
import subprocess
import urllib.error
import urllib.request

root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root)]
compose+=shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
base=os.environ.get('FOUNDATION_TEST_URL','http://127.0.0.1:8110')
origin='http://127.0.0.1:8110'
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'


def code(source, payload=None):
    # Synthetic secrets stay in memory/stdin and are not printed to CI logs.
    script='import json,os\nfrom app.database import make_engine\nfrom app.identity.service import query\n'
    script+='payload=json.loads('+repr(json.dumps(payload))+')\n'+source
    result=subprocess.run([*compose,'exec','-T','api','python','-'],input=script,text=True,capture_output=True)
    if result.returncode:
        raise AssertionError('Identity database test helper failed: '+result.stderr[-600:])
    return json.loads(result.stdout)


class Browser:
    def __init__(self): self.cookies={}

    def request(self,method,path,data=None,expected=200,*,csrf=True,request_origin=origin):
        headers={'Origin':request_origin,'Content-Type':'application/json'}
        if self.cookies:
            headers['Cookie']='; '.join(k+'='+v for k,v in self.cookies.items())
        if csrf and '__Host-ut_csrf' in self.cookies:
            headers['X-CSRF-Token']=self.cookies['__Host-ut_csrf']
        req=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers,method=method)
        try: response=urllib.request.urlopen(req,timeout=20)
        except urllib.error.HTTPError as error: response=error
        with response:
            raw=response.read()
            assert response.status==expected,(method,path,response.status,expected)
            assert response.headers['Cache-Control']=='no-store'
            for header in response.headers.get_all('Set-Cookie',[]):
                cookies=SimpleCookie();cookies.load(header)
                for name,value in cookies.items():
                    assert value['secure'] and value['samesite']=='strict' and value['path']=='/'
                    assert not value['domain']
                    if name=='__Host-ut_session': assert value['httponly']
                    if value['max-age']=='0': self.cookies.pop(name,None)
                    else: self.cookies[name]=value.value
            return json.loads(raw) if raw else {}


fixture=code('''
from app.identity.security import hash_password,encryption_key,new_token,otp_counter
from app.identity.service import audit,recovery_codes
import uuid,pyotp
identifier=uuid.uuid4();secret=pyotp.random_base32();password='Admin integration passphrase 2026!'
cipher=encryption_key(os.environ['IDENTITY_KEY_FILE'])
with make_engine().begin() as db:
    query(db,"INSERT INTO staging.identity_users(id,email,display_name,role,password_hash,mfa_secret) VALUES (:id,'admin@example.invalid','Admin','admin',:hash,:secret)",id=identifier,hash=hash_password(password),secret=cipher.encrypt(secret.encode()).decode())
    audit(db,identifier,'test.fixture',identifier)
    codes=recovery_codes(db,identifier)
print(json.dumps({'id':str(identifier),'password':password,'factor':pyotp.TOTP(secret).now(),'codes':codes}))
''')
admin=Browser();anonymous=Browser()
anonymous.request('GET','/api/admin/users',expected=401)
anonymous.request('POST','/api/auth/login',{'email':'admin@example.invalid','password':fixture['password']},expected=403,request_origin='https://attacker.invalid')
anonymous.request('POST','/api/auth/register',{},expected=404)
for email in ['admin@example.invalid','missing@example.invalid']:
    response=anonymous.request('POST','/api/auth/login',{'email':email,'password':'wrong password'},expected=401)
    assert response['detail']=='Identifiants invalides'
admin.request('POST','/api/auth/login',{'email':'admin@example.invalid','password':fixture['password'],'factor':fixture['factor']})
assert 'session_token' not in admin.request('GET','/api/auth/me')
# Replaying a previously accepted TOTP must fail even with the correct password.
anonymous.request('POST','/api/auth/login',{'email':'admin@example.invalid','password':fixture['password'],'factor':fixture['factor']},expected=401)
admin.request('POST','/api/admin/invitations',{'email':'blocked@example.invalid','display_name':'Blocked','role':'agent'},expected=403,csrf=False)
admin.request('POST','/api/admin/invitations',{'email':'bad@example.invalid','display_name':'Bad','role':'superuser'},expected=422)
admin.request('PATCH','/api/admin/users/'+fixture['id'],{'is_active':False},expected=409)

invitation=admin.request('POST','/api/admin/invitations',{'email':'agent@example.invalid','display_name':'Agent','role':'agent'},expected=201)
assert 'token' not in json.dumps(admin.request('GET','/api/admin/invitations'))
agent=Browser()
body=agent.request('POST','/api/auth/invitations/accept',{'token':invitation['token'],'password':'Agent integration passphrase 2026!'})
agent_id=body['user']['id'];assert body['mfa_enrollment_required'] is False
anonymous.request('POST','/api/auth/invitations/accept',{'token':invitation['token'],'password':'Agent integration passphrase 2026!'},expected=400)
agent.request('GET','/api/admin/users',expected=403)
agent.request('GET','/api/admin/audit',expected=403)
for path in ['/api/contacts','/api/imports','/api/contacts/00000000-0000-0000-0000-000000000001/history','/api/imports/00000000-0000-0000-0000-000000000001/rows']:
    agent.request('GET',path,expected=403)
agent.request('POST','/api/imports',{'id':'00000000-0000-0000-0000-000000000001','filename':'forbidden.csv'},expected=403)
agent.request('POST','/api/imports/00000000-0000-0000-0000-000000000001/confirm',{},expected=403)
agent.request('POST','/api/admin/invitations',{'email':'forbidden@example.invalid','display_name':'X','role':'admin'},expected=403)
old=agent.cookies.copy()
agent.request('POST','/api/auth/password',{'current_password':'Agent integration passphrase 2026!','new_password':'Changed agent passphrase 2026!'})
old_browser=Browser();old_browser.cookies=old;old_browser.request('GET','/api/auth/me',expected=401)
assert old['__Host-ut_session']!=agent.cookies['__Host-ut_session']
admin.request('POST','/api/admin/users/'+agent_id+'/revoke-sessions',{})
agent.request('GET','/api/auth/me',expected=401)
agent.request('POST','/api/auth/login',{'email':'agent@example.invalid','password':'Changed agent passphrase 2026!'})
reset=admin.request('POST','/api/admin/users/'+agent_id+'/password-reset',{})
agent.request('GET','/api/auth/me',expected=401)
agent.request('POST','/api/auth/password-reset',{'token':reset['token'],'password':'Recovered agent passphrase 2026!'})
anonymous.request('POST','/api/auth/password-reset',{'token':reset['token'],'password':'Recovered agent passphrase 2026!'},expected=400)
admin.request('PATCH','/api/admin/users/'+agent_id,{'is_active':False})
agent.request('GET','/api/auth/me',expected=401)
anonymous.request('POST','/api/auth/login',{'email':'agent@example.invalid','password':'Recovered agent passphrase 2026!'},expected=401)

# Renewing or revoking invitations immediately invalidates previously issued tokens.
for email,action in [('revoked@example.invalid','revoke'),('expired@example.invalid','expire')]:
    invitation=admin.request('POST','/api/admin/invitations',{'email':email,'display_name':'Unused','role':'agent'},expected=201)
    if action=='revoke': admin.request('DELETE','/api/admin/invitations/'+invitation['id'])
    else: code("with make_engine().begin() as db: query(db,\"UPDATE staging.identity_invitations SET expires_at=now()-interval '1 second' WHERE id=:id\",id=payload)\nprint('null')",invitation['id'])
    anonymous.request('POST','/api/auth/invitations/accept',{'token':invitation['token'],'password':'Unused invitation passphrase 2026!'},expected=400)

invitation=admin.request('POST','/api/admin/invitations',{'email':'race@example.invalid','display_name':'Race','role':'agent'},expected=201)
def race(_):
    client=Browser()
    try:
        client.request('POST','/api/auth/invitations/accept',{'token':invitation['token'],'password':'Concurrent invitation passphrase 2026!'})
        return 200
    except AssertionError as error:
        assert error.args[0][2]==400
        return 400
with ThreadPoolExecutor(max_workers=2) as pool: assert sorted(pool.map(race,range(2)))==[200,400]

# Admin invitations provide only enrollment access until MFA is confirmed.
invitation=admin.request('POST','/api/admin/invitations',{'email':'second-admin@example.invalid','display_name':'Second Admin','role':'admin'},expected=201)
second=Browser();accepted=second.request('POST','/api/auth/invitations/accept',{'token':invitation['token'],'password':'Second admin passphrase 2026!'})
assert accepted['mfa_enrollment_required'] is True
second.request('GET','/api/admin/users',expected=403)
secret=second.request('POST','/api/auth/mfa/enroll',{})
second.request('POST','/api/auth/mfa/confirm',{'code':'abcdef'},expected=400)
factor=code('import pyotp\nprint(json.dumps(pyotp.TOTP(payload).now()))',secret['secret'])
old=second.cookies.copy()
confirmed=second.request('POST','/api/auth/mfa/confirm',{'code':factor})
assert len(confirmed['recovery_codes'])==8
assert old['__Host-ut_session']!=second.cookies['__Host-ut_session']
assert second.request('GET','/api/admin/users')['users']
second.request('POST','/api/auth/logout',{})
second.request('GET','/api/auth/me',expected=401)
second.request('POST','/api/auth/login',{'email':'second-admin@example.invalid','password':'Second admin passphrase 2026!','factor':confirmed['recovery_codes'][0]})
anonymous.request('POST','/api/auth/login',{'email':'second-admin@example.invalid','password':'Second admin passphrase 2026!','factor':confirmed['recovery_codes'][0]},expected=401)
# Password-reset tokens never substitute for an administrator's MFA factor.
admin_reset=second.request('POST','/api/admin/users/'+fixture['id']+'/password-reset',{})
admin.request('GET','/api/auth/me',expected=401)
anonymous.request('POST','/api/auth/password-reset',{'token':admin_reset['token'],'password':'Recovered admin passphrase 2026!'},expected=400)
admin.request('POST','/api/auth/password-reset',{'token':admin_reset['token'],'password':'Recovered admin passphrase 2026!','factor':fixture['codes'][0]})
second.request('POST','/api/auth/logout-all',{})
second.request('GET','/api/auth/me',expected=401)

# An idle session and absolute expiration both fail closed.
for column in ['last_seen_at','expires_at']:
    agent2=Browser();agent2.request('POST','/api/auth/login',{'email':'race@example.invalid','password':'Concurrent invitation passphrase 2026!'})
    code("with make_engine().begin() as db: query(db,\"UPDATE staging.identity_sessions SET "+column+"=now()-interval '13 hours' WHERE token_hash=:hash\",hash=payload)\nprint('null')",__import__('hashlib').sha256(agent2.cookies['__Host-ut_session'].encode()).hexdigest())
    agent2.request('GET','/api/auth/me',expected=401)

for _ in range(10): anonymous.request('POST','/api/auth/login',{'email':'throttled@example.invalid','password':'Wrong testing passphrase'},expected=401)
anonymous.request('POST','/api/auth/login',{'email':'throttled@example.invalid','password':'Wrong testing passphrase'},expected=429)
invalid=anonymous.request('POST','/api/auth/invitations/accept',{'token':'sensitive-token','password':'sensitive-password'},expected=422)
assert 'sensitive-' not in json.dumps(invalid)
events=admin.request('GET','/api/admin/audit')['events'];assert events
assert any(e['action']=='mfa.enrolled' for e in events)
code('''
from sqlalchemy.exc import DBAPIError
with make_engine().connect() as db:
    row=query(db,"SELECT password_hash,mfa_secret FROM staging.identity_users WHERE email='admin@example.invalid'").one()
    assert row.password_hash.startswith('$argon2id$')
    assert not row.mfa_secret.startswith('otpauth:')
for statement in ['UPDATE staging.identity_audit SET action=action','DELETE FROM staging.identity_audit','DELETE FROM staging.identity_users']:
    try:
        with make_engine().begin() as db: query(db,statement)
    except DBAPIError: pass
    else: raise AssertionError('Runtime modified protected identity records')
print('null')
''')
# A valid but incorrect encryption key must prevent a healthy deployment.
originals=code('''
from cryptography.fernet import Fernet
with make_engine().begin() as db:
    rows=query(db,'SELECT id,mfa_secret FROM staging.identity_users WHERE mfa_secret IS NOT NULL').mappings().all()
    original=[{'id':str(r['id']),'secret':r['mfa_secret']} for r in rows]
    wrong=Fernet(Fernet.generate_key()).encrypt(b'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA').decode()
    query(db,'UPDATE staging.identity_users SET mfa_secret=:wrong WHERE mfa_secret IS NOT NULL',wrong=wrong)
print(json.dumps(original))
''')
try:
    anonymous.request('GET','/health/ready',expected=503)
finally:
    code("with make_engine().begin() as db:\n    for row in payload: query(db,'UPDATE staging.identity_users SET mfa_secret=:secret WHERE id=:id',**row)\nprint('null')",originals)
anonymous.request('GET','/health/ready')

# Concurrent attempts to disable both administrators must leave one enrolled admin.
def disable(identifier):
    client=Browser();client.cookies=admin.cookies.copy()
    try:
        client.request('PATCH','/api/admin/users/'+identifier,{'is_active':False})
        return 200
    except AssertionError as error:
        status=error.args[0][2]
        assert status in {401,409}
        return status
with ThreadPoolExecutor(max_workers=2) as pool:
    outcomes=list(pool.map(disable,[fixture['id'],accepted['user']['id']]))
assert outcomes.count(200)==1
assert code("with make_engine().connect() as db: count=query(db,\"SELECT count(*) FROM staging.identity_users WHERE role='admin' AND is_active AND mfa_secret IS NOT NULL\").scalar_one()\nprint(json.dumps(count))")==1
print('Invitations, concurrent acceptance, admin MFA/replay/recovery, roles, CSRF/origin, cookie rotation, revocation, password recovery, expiry, throttling and audit permissions: PASS')
