"""Real runtime-role PG checks for the explicitly authorized enrollment operator.

Run in a disposable migrated Compose API container with this script and the
operator mounted read-only. Never run against a managed application database.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
import sys
import uuid

from fastapi import HTTPException
from app.campaigns import service
from app.database import make_engine
from app.identity.service import query

assert os.environ['DB_HOST'] == 'db'
assert os.environ['COMMUNICATIONS_MODE'] == 'disabled'
spec = importlib.util.spec_from_file_location('operator_batches', '/enroll_batches.py')
operator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operator)
engine = make_engine()
actor, campaign, source, old_source = [uuid.uuid4() for _ in range(4)]
campaign_name = 'Synthetic operator ' + str(campaign)
checksum = 'a'*64
args = (engine, actor, campaign, source, checksum, campaign_name)
stages = {}
with engine.begin() as db:
    assert query(db, "SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one() == 'synthetic_only'
    query(db, "SET LOCAL statement_timeout='15s'")
    query(db, "INSERT INTO staging.identity_users(id,email,display_name,role,password_hash) VALUES (:id,:email,'Synthetic operator','admin','synthetic')", id=actor, email=str(actor)+'@example.invalid')
    query(db, "INSERT INTO staging.campaigns(id,name,timezone,created_by) VALUES (:id,:name,'America/Toronto',:actor)", id=campaign, name=campaign_name, actor=actor)
    for position, (name, kind, color) in enumerate(service.DEFAULT_STAGES):
        stage = uuid.uuid4(); stages[kind] = stage
        query(db, 'INSERT INTO staging.campaign_stages(id,campaign_id,name,kind,color,position) VALUES (:id,:campaign,:name,:kind,:color,:position)', id=stage, campaign=campaign, name=name, kind=kind, color=color, position=position)
    for job, total in [(source, 1005), (old_source, 0)]:
        query(db, "INSERT INTO staging.contact_imports(id,created_by,filename,encoding,status,source_key,source_sha256,total,processed,invalid) VALUES (:id,:actor,'synthetic.csv','utf-8-sig','completed',:key,:hash,:total,:total,:invalid)", id=job, actor=actor, key=str(job), hash=checksum, total=total, invalid=4 if total else 0)
    query(db, "INSERT INTO staging.contacts(id,phone,profile,do_not_contact,non_interested) SELECT md5(:seed||i)::uuid,'+1999'||lpad(i::text,7,'0'),'{\"display_name\":\"Émilie\"}',i=3,i=4 FROM generate_series(1,1000)i", seed=str(source))
    query(db, "INSERT INTO staging.contact_import_rows(import_id,row_number,profile,duplicate_in_file,outcome,contact_id) SELECT :source,i,'{}',i=1001,CASE WHEN i>1001 THEN 'invalid' ELSE 'created' END,CASE WHEN i>1001 THEN NULL ELSE md5(:seed||CASE WHEN i=1001 THEN 1 ELSE i END)::uuid END FROM generate_series(1,1005)i", source=source, seed=str(source))
    query(db, "INSERT INTO staging.campaign_contacts(campaign_id,contact_id,stage_id,source_import_id,is_active,version) SELECT :campaign,md5(:seed||i)::uuid,:stage,:old,i=1,4 FROM generate_series(1,2)i", campaign=campaign, seed=str(source), stage=stages['other'], old=old_source)
    contact1 = query(db, "SELECT md5(:seed||1)::uuid", seed=str(source)).scalar_one()
    before_card = dict(query(db, 'SELECT * FROM staging.campaign_contacts WHERE campaign_id=:id AND contact_id=:contact', id=campaign, contact=contact1).mappings().one())
    contacts_before = query(db, 'SELECT row_to_json(c)::text FROM staging.contacts c ORDER BY id').scalars().all()
    imports_before = query(db, 'SELECT row_to_json(c)::text FROM staging.contact_imports c ORDER BY id').scalars().all()
    rows_before = query(db, 'SELECT row_to_json(c)::text FROM staging.contact_import_rows c ORDER BY import_id,row_number').scalars().all()

before = operator.inspect(*args)
assert before['rows'] == 1005 and before['unique_contacts'] == 1000 and before['valid_rows'] == 1001
assert before['active_memberships'] == 1 and before['inactive_memberships'] == 1
sys.argv = ['/enroll_batches.py', '--actor', str(actor), '--campaign', str(campaign), '--import-id', str(source), '--source-sha256', checksum, '--campaign-name', campaign_name]
with redirect_stdout(io.StringIO()) as output:
    operator.main()
assert json.loads(output.getvalue())['apply'] is False
assert operator.inspect(*args) == before
print('PASS: completed-source validation, default dry run, duplicate/invalid counts', flush=True)

real_audit = operator.audit
def fail_audit(*_):
    raise RuntimeError('Synthetic injected audit failure')
operator.audit = fail_audit
try:
    operator.run_batch(*args, 0, 500)
except RuntimeError as error:
    assert 'Synthetic injected' in str(error)
else:
    raise AssertionError('Injected failure did not fail')
finally:
    operator.audit = real_audit
assert operator.inspect(*args) == before
with engine.connect() as db:
    assert query(db, 'SELECT count(*) FROM staging.campaign_events WHERE campaign_id=:id', id=campaign).scalar_one() == 0
print('PASS: interrupted transaction rolls back memberships, reactivation and all immutable events', flush=True)

with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(lambda _: operator.run_batch(*args, 0, 500), range(2)))
assert sorted(r['replayed'] for r in results) == [False, True]
assert all(r['added'] == 499 and r['total'] == 500 for r in results)
second = operator.run_batch(*args, 500, 1000)
third = operator.run_batch(*args, 1000, 1005)
assert second['added'] == 500 and second['existing'] == 0
assert third['added'] == 0 and third['existing'] == 1
assert operator.run_batch(*args, 500, 1000)['replayed']
after = operator.inspect(*args)
assert after['active_memberships'] == 1000 and after['missing_memberships'] == after['inactive_memberships'] == 0
print('PASS: simultaneous same-batch delivery, resume/replay, cross-batch duplicates, invalid-row exclusion', flush=True)

with engine.connect() as db:
    assert dict(query(db, 'SELECT * FROM staging.campaign_contacts WHERE campaign_id=:id AND contact_id=:contact', id=campaign, contact=contact1).mappings().one()) == before_card
    for number, kind in [(3, 'do_not_contact'), (4, 'non_interested')]:
        row = query(db, "SELECT stage_id,source_import_id FROM staging.campaign_contacts WHERE campaign_id=:campaign AND contact_id=md5(:seed||:number)::uuid", campaign=campaign, seed=str(source), number=str(number)).mappings().one()
        assert row['stage_id'] == stages[kind] and row['source_import_id'] == source
    reactivated = query(db, "SELECT * FROM staging.campaign_contacts WHERE campaign_id=:campaign AND contact_id=md5(:seed||2)::uuid", campaign=campaign, seed=str(source)).mappings().one()
    assert reactivated['is_active'] and reactivated['version'] == 5 and reactivated['stage_id'] == stages['new'] and reactivated['source_import_id'] == old_source
    assert query(db, 'SELECT row_to_json(c)::text FROM staging.contacts c ORDER BY id').scalars().all() == contacts_before
    assert query(db, 'SELECT row_to_json(c)::text FROM staging.contact_imports c ORDER BY id').scalars().all() == imports_before
    assert query(db, 'SELECT row_to_json(c)::text FROM staging.contact_import_rows c ORDER BY import_id,row_number').scalars().all() == rows_before
    events = query(db, "SELECT details FROM staging.campaign_events WHERE campaign_id=:id AND action='contact.enrolled'", id=campaign).scalars().all()
    assert len(events) == 999 and all(e['source_import_id'] == str(source) for e in events)
    assert query(db, "SELECT count(*) FROM staging.campaign_events WHERE campaign_id=:id AND action='contacts.import_batch_enrolled'", id=campaign).scalar_one() == 3
    assert query(db, "SELECT count(*) FROM staging.identity_audit WHERE subject_id=:id AND action='campaign.contacts_enrolled'", id=campaign).scalar_one() == 3
print('PASS: active-stage/order/version preservation; inactive reactivation; global restrictions; import provenance; unchanged contacts/imports/rows; exact-once audit', flush=True)

for label, replacements, exception in [
    ('source checksum mismatch', {4: 'b'*64}, RuntimeError),
    ('campaign name mismatch', {5: 'Wrong campaign'}, RuntimeError),
    ('wrong source owner', {1: uuid.uuid4()}, Exception),
]:
    altered = list(args)
    for index, value in replacements.items(): altered[index] = value
    try:
        operator.run_batch(*altered, 0, 500)
    except exception:
        pass
    else:
        raise AssertionError(label + ' accepted')
with engine.begin() as db:
    query(db, 'UPDATE staging.identity_users SET role=\'agent\' WHERE id=:id', id=actor)
try:
    operator.run_batch(*args, 0, 500)
except HTTPException as error:
    assert error.status_code == 403
else:
    raise AssertionError('Agent actor accepted')
with engine.begin() as db:
    query(db, "UPDATE staging.identity_users SET role='admin' WHERE id=:id", id=actor)
    query(db, 'UPDATE staging.campaigns SET is_active=false WHERE id=:id', id=campaign)
try:
    operator.run_batch(*args, 0, 500)
except HTTPException as error:
    assert error.status_code == 409
else:
    raise AssertionError('Archived campaign accepted')
try:
    operator.run_batch(*args, 0, 501)
except ValueError:
    pass
else:
    raise AssertionError('Oversized batch accepted')
print('PASS: invalid owner/checksum/campaign identity, non-admin, archived campaign, oversized batch rejected', flush=True)
engine.dispose()
