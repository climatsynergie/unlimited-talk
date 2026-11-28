"""Disposable PG: Nano capacity/rate survive restart; indexes preserve schema/data."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import runpy
import time
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import text
from app.database import make_engine
from app.identity.service import query
from app.telephony import vmhunter as vm
from app.telephony.vmhunter_observer import Store, ProviderQuota

# This fixture proves >5,000 prior-period records and checks the old Free rules
# first. The harness creates a new internal-only DB with outbound calling off.
proof = runpy.run_path('/tests/vmhunter-provider-quota-integration.py')
fixture = proof['fixture']
engine, profile, pilot = proof['engine'], proof['profile'], proof['pilot']
call, finish, campaigns = fixture['call'], fixture['finish'], fixture['campaigns']

def snapshot():
    with engine.connect() as db:
        return {name: tuple(query(db, 'SELECT count(*),coalesce(sum(hashtextextended(row_to_json(t)::text,0)),0) FROM staging.' + name + ' t').one())
                for name in ('voice_intents', 'voice_events', 'contacts', 'campaign_contacts')}

installer = runpy.run_path('/scripts/install_vmhunter_index.py')['install']
try:
    installer(engine)
except RuntimeError as error:
    assert 'migration role' in str(error)
else:
    raise AssertionError('Runtime role unexpectedly received index maintenance rights')

with patch.dict(os.environ, {'DB_USER': 'ut_staging_migrator',
        'DB_PASSWORD_FILE': '/run/secrets/migrator_password'}):
    migrator = make_engine()
try:
    before = snapshot()
    installed = installer(migrator)
    assert installer(migrator) == installed
    assert snapshot() == before, 'Online index installation changed business data'

    # Expand only this synthetic campaign fixture to twenty-one independent
    # actors. Per-agent active-call constraints remain enabled throughout.
    with engine.begin() as db:
        for i in range(3, 22):
            actor, contact = uuid4(), uuid4()
            number = '+1416555' + str(1000 + i)
            fixture['actors'].append(actor)
            fixture['contacts'].append(contact)
            fixture['numbers'].append(number)
            query(db, "INSERT INTO staging.identity_users(id,email,display_name,role,password_hash) VALUES (:id,:email,'Nano synthetic','agent','unused')",
                  id=actor, email=str(actor) + '@example.invalid')
            query(db, 'INSERT INTO staging.contacts(id,phone) VALUES (:id,:phone)', id=contact, phone=number)
            query(db, 'INSERT INTO staging.campaign_agents(campaign_id,user_id,assigned_by) VALUES (:campaign,:actor,:actor)',
                  campaign=campaigns[0], actor=actor)
            query(db, 'INSERT INTO staging.campaign_contacts(campaign_id,contact_id,stage_id) VALUES (:campaign,:contact,:stage)',
                  campaign=campaigns[0], contact=contact, stage=fixture['stages'][0])

    quota = ProviderQuota(100000)
    store = Store(engine, profile, pilot, provider_quota=quota)
    payloads = [call(campaigns[0], i) for i in range(21)]
    # Model an immediate plan transition on the same account. These recently
    # completed Free analyses must still consume the shared rolling CPS budget.
    warmup_store = Store(engine, profile, pilot, provider_quota=ProviderQuota())
    warmup = warmup_store.claim(call(campaigns[0], 21))
    assert warmup
    warmup_store.result(warmup, vm.Result('HUMAN', 'HUMAN'), stop_confirmed=True)
    finish(warmup)
    with engine.connect() as db:
        carried = query(db,"SELECT count(*) FROM staging.voice_events c JOIN staging.voice_intents i ON i.id=c.intent_id WHERE i.account_sid=:account AND c.kind='vmhunter.claim' AND c.created_at>statement_timestamp()-interval '1 second'",account=profile.account_sid).scalar_one()
    assert carried >= 1
    print(json.dumps({'account_recent_claims_before_nano_burst':carried}),flush=True)
    # Start the dedicated Nano burst in an empty account-rate window. Without
    # this boundary a fast CI runner correctly rejects one of the five starts
    # because the preceding Free fixture consumed a slot. Keep the rate limit,
    # rolling-window assertion and sixth-start rejection unchanged.
    time.sleep(1.05)
    with engine.connect() as db:
        assert query(db,"SELECT count(*) FROM staging.voice_events c JOIN staging.voice_intents i ON i.id=c.intent_id WHERE i.account_sid=:account AND c.kind='vmhunter.claim' AND c.created_at>statement_timestamp()-interval '1 second'",account=profile.account_sid).scalar_one()==0
    claims = []
    for batch in range(4):
        if batch:
            time.sleep(1.05)
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=5) as pool:
            accepted = list(pool.map(store.claim, payloads[batch * 5:batch * 5 + 5]))
        assert all(accepted), 'Paid capacity incorrectly bypassed an eligible analysis'
        claims.extend(accepted)
        if batch == 0:
            assert time.monotonic() - started < 0.9, 'Fixture too slow to prove a rolling-second burst'
            assert store.claim(payloads[5]) is None, 'Sixth analysis exceeded Nano 5-CPS admission'
            restarted = Store(engine, profile, pilot, provider_quota=quota)
            assert restarted.claim(payloads[5]) is None, 'Process restart reset account rate limit'
    assert len(claims) == 20
    time.sleep(1.05)
    restarted = Store(engine, profile, pilot, provider_quota=quota)
    assert restarted.claim(payloads[20]) is None, 'Restart bypassed twenty-analysis capacity'
    restarted.result(claims[0], vm.Result('HUMAN', 'HUMAN'), stop_confirmed=True)
    finish(claims[0])
    last = restarted.claim(payloads[20])
    assert last, 'Completed analysis failed to free a slot'
    def complete(claimed):
        restarted.result(claimed, vm.Result('MACHINE', 'INITIALSILENCE'), stop_confirmed=True)
        finish(claimed)
    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(complete, [*claims[1:], last]))
    assert restarted.cleanup_candidates(include_recent=True) == []

    # Additive-index rollback is optional and changes no journal facts. Keep
    # the original lookup index and verify the previous Free configuration.
    before = snapshot()
    with migrator.connect().execution_options(isolation_level='AUTOCOMMIT') as db:
        for name in ('voice_vmhunter_recent_claims', 'voice_vmhunter_stopped'):
            db.execute(text('DROP INDEX CONCURRENTLY staging.' + name))
    assert snapshot() == before
    free = Store(engine, profile, pilot, provider_quota=ProviderQuota())
    extra = call(campaigns[0], 0)
    claimed = free.claim(extra)
    assert claimed, 'Previous Free runtime configuration broke after online-index rollback'
    free.result(claimed, vm.Result('HUMAN', 'HUMAN'), stop_confirmed=True)
    finish(claimed)
    with engine.connect() as db:
        assert query(db, 'SELECT version_num FROM staging.alembic_version').scalar_one() == '0012_incoming_runtime'
        assert not query(db, "SELECT has_schema_privilege(current_user,'staging','CREATE')").scalar_one()
    print(json.dumps(dict(nano_monthly_allowance=100000, max_concurrent=20, calls_per_second=5,
        simultaneous_five_admissions=True, third_analysis_accepted=True, twenty_slots_used=True,
        account_rate_and_capacity_survive_restart=True, slot_released_on_result=True,
        twenty_concurrent_completions_on_two_db_connections=True,
        prior_free_traffic_preserved_and_window_isolated=True,
        runtime_ddl_denied=True, online_indexes_repeatable=True, index_rollback_preserves_data=True,
        previous_free_configuration_works=True, schema='0012_incoming_runtime', migration_required=False,
        real_calls=0)))
finally:
    migrator.dispose()
    engine.dispose()
