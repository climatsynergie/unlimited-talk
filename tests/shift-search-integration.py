"""300k synthetic contacts: real route authorization, exact search and index plans."""
from datetime import datetime,timezone
import importlib.util
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from starlette.requests import Request
from app.database import make_engine
from app.identity.security import COOKIE,digest,new_token
from app.identity.service import query
from app.contacts import routes as contacts
from app.telephony import recording_routes as history

assert os.environ['DB_HOST']=='db' and os.environ['COMMUNICATIONS_MODE']=='disabled'
engine=make_engine()
with engine.connect() as db:
    assert query(db,"SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one()=='synthetic_only'
token=new_token();actor=uuid4();account='AC'+uuid4().hex
# Bulk fixture construction uses the migrator's existing 60s budget; all
# application route checks below retain the runtime's original 3s deadline.
with patch.dict(os.environ,{'DB_USER':'ut_staging_migrator','DB_PASSWORD_FILE':'/run/secrets/migrator_password'}):
    migrator=make_engine()
with migrator.begin() as db:
    query(db,"INSERT INTO staging.identity_users(id,email,display_name,role,password_hash,mfa_secret) VALUES (:id,:email,'Search fixture','admin','unused','synthetic-only')",id=actor,email=str(actor)+'@example.invalid')
    query(db,"INSERT INTO staging.identity_sessions(token_hash,csrf_hash,user_id,mfa_verified,expires_at) VALUES (:hash,:csrf,:id,true,clock_timestamp()+interval '1 hour')",hash=digest(token),csrf=digest(new_token()),id=actor)
    for start in range(1,300001,10000):
        query(db,"""INSERT INTO staging.contacts(id,phone,profile,created_at)
        SELECT gen_random_uuid(),'+1416'||lpad(n::text,7,'0'),
          jsonb_build_object('display_name','Personne '||n,'first_name','Prénom','last_name','Famille '||n,
            'city','Montréal','address','Adresse synthétique '||n),
          clock_timestamp()-n*interval '1 second' FROM generate_series(CAST(:start AS integer),CAST(:end AS integer)) n""",start=start,end=start+9999)
    special=uuid4()
    query(db,"""INSERT INTO staging.contacts(id,phone,profile) VALUES (:id,'+14165559999',CAST(:profile AS jsonb))""",
        id=special,profile=json.dumps(dict(display_name='Zoé "Ouest" A%B_C',first_name='Zoé',last_name='Ouest',city='Rare Needle City')))
    for offset in range(0,36000,6000):
        query(db,"""INSERT INTO staging.voice_intents(id,actor_id,contact_id,session_hash,profile_hash,account_sid,
      application_sid,caller_number,destination,state,parent_call_sid,child_call_sid,created_at,expires_at,consumed_at,finished_at,outcome)
      SELECT gen_random_uuid(),:actor,c.id,:session,repeat('f',64),:account,'AP'||md5(c.id::text),'+14165550000',c.phone,
        'finished','CA'||md5(c.id::text||'p'),'CA'||md5(c.id::text),c.created_at,c.created_at+interval '4 minutes',
        c.created_at,c.created_at+interval '1 minute','completed'
      FROM staging.contacts c ORDER BY c.created_at DESC,c.id LIMIT 6000 OFFSET :offset""",actor=actor,session=digest(token),account=account,offset=offset)
    foreign=uuid4()
    query(db,"INSERT INTO staging.identity_users(id,email,display_name,role,password_hash) VALUES (:id,:email,'Foreign fixture','agent','unused')",id=foreign,email=str(foreign)+'@example.invalid')
    query(db,"UPDATE staging.voice_intents SET actor_id=:actor,session_hash=repeat('0',64) WHERE id=(SELECT id FROM staging.voice_intents ORDER BY created_at DESC LIMIT 1)",actor=foreign)

request=Request({'type':'http','method':'GET','path':'/api/contacts','headers':[(b'cookie',(COOKIE+'='+token).encode())],
    'app':SimpleNamespace(state=SimpleNamespace(engine=engine))})
captured=[]
def capture(db,statement,**values):
    if 'FROM staging.contacts' in statement or 'WITH page AS MATERIALIZED' in statement:
        captured.append((statement,values))
    return query(db,statement,**values)

spec=importlib.util.spec_from_file_location('query_indexes','/scripts/install_query_indexes.py')
indexes=importlib.util.module_from_spec(spec);spec.loader.exec_module(indexes)
try:indexes.install(engine)
except RuntimeError as error:assert 'migration role' in str(error)
else:raise AssertionError('Runtime role must not install query indexes')
result=indexes.install(migrator);assert len(result['indexes'])==2
assert indexes.install(migrator)==result,'Online installation must be idempotent'
with migrator.begin() as db:query(db,'ANALYZE staging.contacts');query(db,'ANALYZE staging.voice_intents')

def plan(sql,values):
    with engine.connect() as db:
        query(db,'SET TRANSACTION READ ONLY');query(db,"SET LOCAL statement_timeout='10000ms'")
        value=query(db,'EXPLAIN (ANALYZE,FORMAT JSON) '+sql,**values).scalar_one()[0]
    return value
def nodes(value):
    yield value
    for child in value.get('Plans',[]):yield from nodes(child)

with patch.object(contacts,'query',side_effect=capture):
    first=contacts.contacts(request,search='',offset=0)
assert len(first['items'])==50 and first['has_more']
browse=plan(*captured[-1])
assert any(n.get('Index Name')=='contacts_directory_order' for n in nodes(browse['Plan']))
for term in ('Rare Needle City','A%B_C','%','_','Zoé','\\','not-present-long-needle',"' OR 1=1 --"):
    with patch.object(contacts,'query',side_effect=capture):
        found=contacts.contacts(request,search=term,offset=0)
    with engine.connect() as db:
        original=list(query(db,"""SELECT id FROM staging.contacts
          WHERE strpos(lower(phone||' '||profile::text),lower(:search))>0
          ORDER BY created_at DESC,id LIMIT 51""",search=term).scalars())
    assert [row['id'] for row in found['items']]==original[:50],('Literal contact search changed',term)
    assert found['has_more']==(len(original)>50)
    if term=='Rare Needle City':
        search_plan=plan(*captured[-1])
        assert any(n.get('Index Name')=='contacts_directory_search' for n in nodes(search_plan['Plan']))

def calls(term='',**changes):
    args=dict(before_created_at=None,before_id=None,q=term,outcome='',recordings_only=False,actor_id=None,
        destination='',from_at=None,until_at=None,recording_min_seconds=None)
    args.update(changes)
    with patch.object(history,'query',side_effect=capture):return history.calls(request,**args)

page=calls();sql=next(item for item in reversed(captured) if 'WITH page AS MATERIALIZED' in item[0])
history_plan=plan(*sql)
assert len(page['items'])==20 and page['next_cursor']
assert not any(n.get('Node Type') in {'Seq Scan','Parallel Seq Scan'} and n.get('Relation Name')=='contacts'
    for n in nodes(history_plan['Plan'])),'Default call history scanned the whole imported directory'
cursor=page['next_cursor']
following=calls(before_created_at=datetime.fromisoformat(cursor['created_at']),before_id=cursor['id'])
assert not ({r['id'] for r in page['items']} & {r['id'] for r in following['items']})
for term in ('Zoé "Ouest"','Zoé Ouest','A%B_C'):
    found=calls(term)
    assert len(found['items'])==1 and found['items'][0]['contact_name']=='Zoé "Ouest" A%B_C'
assert not calls('not-present-long-needle')['items']
with engine.begin() as db:
    query(db,"UPDATE staging.identity_users SET role='agent',mfa_secret=NULL WHERE id=:id",id=actor)
try:
    calls(actor_id=uuid4())
    raise AssertionError('Foreign actor history was not forbidden')
except Exception as error:assert getattr(error,'status_code',None)==403
assert all(row['actor_id']==actor for row in calls()['items'])
with engine.connect() as db:
    assert query(db,'SELECT version_num FROM staging.alembic_version').scalar_one()=='0012_incoming_runtime'
print(json.dumps(dict(contacts=300001,calls=36000,literal_search_preserved=True,fullname_and_quotes_preserved=True,
    cursor_pagination=True,agent_scope_enforced=True,concurrent_indexes_idempotent=True,
    browse_execution_ms=browse['Execution Time'],rare_search_execution_ms=search_plan['Execution Time'],
    history_execution_ms=history_plan['Execution Time'],schema_unchanged=True,external_calls=0)),flush=True)
engine.dispose();migrator.dispose()
