"""Executed inside a disposable API only; checks real PG + S3 + Redis recovery."""
import hashlib
import json
import os
import uuid
from types import SimpleNamespace
from sqlalchemy import text
from fastapi import HTTPException
from app.database import make_engine
from app.contacts import service
from app.contacts.csv_input import validate_csv
from app.contacts.storage import client, put_source, read_source
from app.contacts.dispatch import dispatch_once
from app.contacts.tasks import apply, celery
from app.identity.security import COOKIE,CSRF_COOKIE,digest
from app.identity.service import authenticate

assert os.environ['DB_HOST']=='db' and os.environ.get('DB_DEPLOYMENT','local')=='local'
engine=make_engine()
s3,bucket=client()
s3.create_bucket(Bucket=bucket)
actor=uuid.uuid4()
with engine.begin() as db:
    db.execute(text("INSERT INTO staging.identity_users(id,email,display_name,role,password_hash,mfa_secret) VALUES (:id,:email,'Import test','admin','unused','unused')"),dict(id=actor,email=str(actor)+'@example.test'))


def prepare(source, mapping):
    identifier=uuid.uuid4();key='imports/'+str(identifier)+'/source.csv'
    fingerprint=put_source(key,source)
    with engine.begin() as db:
        db.execute(text("""INSERT INTO staging.contact_imports(id,created_by,filename,encoding,status,source_key,source_sha256)
            VALUES (:id,:actor,'synthetic.csv','utf-8-sig','mapping',:key,:hash)"""),dict(id=identifier,actor=actor,key=key,hash=fingerprint))
        result=service.preview(db,service.job(db,identifier,lock=True),mapping)
    assert result['status']=='preview'
    with engine.begin() as db:
        assert db.execute(text('SELECT count(*) FROM staging.contact_import_rows WHERE import_id=:id'),dict(id=identifier)).scalar_one()==result['total']
        db.execute(text("UPDATE staging.contact_imports SET status='queued',confirmed_at=now() WHERE id=:id"),dict(id=identifier))
    return identifier


source=b'telephone,prenom,courriel\n4165550123,Alice,alice@example.test\n4165550123,,\ninvalid,Bad,\n'
identifier=prepare(source,dict(phone='telephone',first_name='prenom',email='courriel'))
# Confirmed outbox survives publication failure.
try:
    dispatch_once(engine,lambda identifier: (_ for _ in ()).throw(ConnectionError()))
except ConnectionError:
    pass
with engine.connect() as db:
    assert db.execute(text('SELECT processed FROM staging.contact_imports WHERE id=:id'),dict(id=identifier)).scalar_one()==0
# Exercise transactional crash: failure after first row work rolls back contacts, history and progress.
original=service.query
calls=0

def crash(db,statement,**values):
    global calls
    result=original(db,statement,**values)
    if 'UPDATE staging.contact_import_rows SET outcome' in statement:
        calls+=1
        if calls==1: raise RuntimeError('Synthetic worker interruption')
    return result
service.query=crash
try:
    try: service.apply_chunk(engine,identifier)
    except RuntimeError: pass
finally: service.query=original
with engine.connect() as db:
    assert db.execute(text("SELECT count(*) FROM staging.contacts WHERE phone='+14165550123'")).scalar_one()==0
assert service.apply_chunk(engine,identifier,limit=1)
# Duplicate delivery + resumption do not repeat committed rows.
assert service.apply_chunk(engine,identifier)
assert not service.apply_chunk(engine,identifier)
with engine.begin() as db:
    row=service.job(db,identifier)
    assert (row['processed'],row['created'],row['unchanged'],row['invalid'])==(3,1,1,1)
    contact=db.execute(text("UPDATE staging.contacts SET do_not_contact=true,non_interested=true WHERE phone='+14165550123' RETURNING id")).scalar_one()
second=prepare(b'telephone,prenom,courriel\n4165550123,Alicia,\n',dict(phone='telephone',first_name='prenom',email='courriel'))
# Real broker publication; the separately running worker consumes JSON task IDs.
dispatch_once(engine,lambda identifier: apply.apply_async(args=[identifier],retry=False))
import time
for _ in range(60):
    with engine.connect() as db:
        row=service.job(db,second)
        if row['status']=='completed': break
    time.sleep(1)
else: raise AssertionError('Worker did not consume import')
with engine.connect() as db:
    c=db.execute(text('SELECT * FROM staging.contacts WHERE id=:id'),dict(id=contact)).mappings().one()
    assert c['do_not_contact'] and c['non_interested']
    assert c['profile']['email']=='alice@example.test' and c['profile']['first_name']=='Alicia'
    assert db.execute(text('SELECT count(*) FROM staging.contact_history WHERE contact_id=:id'),dict(id=contact)).scalar_one()==3
# Source fingerprint mismatch prevents preview/apply from silently accepting replacement.
s3.put_object(Bucket=bucket,Key='tampered.csv',Body=b'changed',ACL='private')
try: read_source('tampered.csv','0'*64)
except ValueError: pass
else: raise AssertionError('Changed source accepted')
s3.delete_object(Bucket=bucket,Key='tampered.csv')
# Background polling checks session validity without extending its idle deadline.
token='a'*43;csrf='b'*43
with engine.begin() as db:
    db.execute(text("INSERT INTO staging.identity_sessions(token_hash,csrf_hash,user_id,mfa_verified,expires_at,last_seen_at) VALUES (:token,:csrf,:actor,true,now()+interval '1 hour',now()-interval '5 minutes')"),dict(token=digest(token),csrf=digest(csrf),actor=actor))
    before=db.execute(text('SELECT last_seen_at FROM staging.identity_sessions WHERE token_hash=:token'),dict(token=digest(token))).scalar_one()
    request=SimpleNamespace(cookies={COOKIE:token,CSRF_COOKIE:csrf},method='GET',headers={})
    authenticate(db,request,touch=False)
    after=db.execute(text('SELECT last_seen_at FROM staging.identity_sessions WHERE token_hash=:token'),dict(token=digest(token))).scalar_one()
    assert before==after
    db.execute(text('DELETE FROM staging.identity_sessions WHERE token_hash=:token'),dict(token=digest(token)))
# Remove only synthetic test identities; contact history intentionally preserves its actor reference.
with engine.begin() as db:
    db.execute(text("UPDATE staging.identity_users SET is_active=false,mfa_secret=NULL WHERE id=:id"),dict(id=actor))
print('Imports: PG crash rollback, duplicate delivery, worker/broker, immutable source, enrichment, restrictions, idle session: PASS')
