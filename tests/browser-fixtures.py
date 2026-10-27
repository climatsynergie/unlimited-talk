"""Synthetic fixtures for local/CI browser tests; refuses managed deployments."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root)]
compose+=shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
if 'db' not in config['services'] or config['services']['api']['environment']['DB_HOST']!='db':
    raise SystemExit('Browser fixtures require disposable local PostgreSQL')
payload=json.load(sys.stdin)
source='''
import json,os,uuid
import pyotp
from app.database import make_engine
from app.identity.security import encryption_key,hash_password,new_token
from app.identity.service import query,recovery_codes,audit
payload=json.loads(PAYLOAD)
engine=make_engine()
cipher=encryption_key(os.environ['IDENTITY_KEY_FILE'])
with engine.begin() as db:
    if payload['op']=='seed':
        identifier=uuid.uuid4();secret=pyotp.random_base32();password=new_token();email='browser-admin-'+uuid.uuid4().hex[:8]+'@example.invalid'
        query(db,"INSERT INTO staging.identity_users(id,email,display_name,role,password_hash,mfa_secret) VALUES (:id,:email,'Admin navigateur','admin',:hash,:secret)",id=identifier,email=email,hash=hash_password(password),secret=cipher.encrypt(secret.encode()).decode())
        codes=recovery_codes(db,identifier);audit(db,identifier,'test.browser_fixture',identifier)
        result={'email':email,'password':password,'factor':pyotp.TOTP(secret).now(),'codes':codes,'id':str(identifier)}
    elif payload['op']=='agent':
        identifier=uuid.uuid4();password=new_token();email='pipeline-agent-'+uuid.uuid4().hex+'@example.invalid'
        query(db,"INSERT INTO staging.identity_users(id,email,display_name,role,password_hash) VALUES (:id,:email,'Agent pipeline','agent',:hash)",id=identifier,email=email,hash=hash_password(password))
        result={'email':email,'password':password,'id':str(identifier)}
    elif payload['op']=='otp':
        result={'code':pyotp.TOTP(payload['secret']).now()}
    elif payload['op']=='expire':
        query(db,"UPDATE staging.identity_sessions SET expires_at=now()-interval '1 second' WHERE user_id=(SELECT id FROM staging.identity_users WHERE email=:email)",email=payload['email'])
        result={'status':'expired'}
    else:
        raise ValueError('Unknown browser fixture operation')
print(json.dumps(result))
'''.replace('PAYLOAD',repr(json.dumps(payload)))
r=subprocess.run([*compose,'exec','-T','api','python','-'],input=source,text=True,capture_output=True)
if r.returncode:
    raise SystemExit('Synthetic browser fixture operation failed')
print(r.stdout.strip())
