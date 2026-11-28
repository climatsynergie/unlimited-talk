"""Disposable journal-scale query regression, equivalence and role boundaries."""
import json
import os
import runpy
import time
from unittest.mock import patch
from sqlalchemy import text

from app.database import make_engine
from app.identity.service import query
from app.telephony.vmhunter_observer import Store, ProviderQuota, CLEANUP_LOOKUP_SQL

proof = runpy.run_path('/tests/vmhunter-provider-quota-integration.py')
engine, profile, pilot = proof['engine'], proof['profile'], proof['pilot']
fixture = proof['fixture']
with patch.dict(os.environ, {'DB_USER':'ut_staging_migrator',
        'DB_PASSWORD_FILE':'/run/secrets/migrator_password'}):
    migrator = make_engine()
installer = runpy.run_path('/scripts/install_vmhunter_index.py')['install']

# Exact former query from 3e01fd9, retained only as a regression comparator.
legacy = """SELECT c.intent_id,c.details FROM staging.voice_events c
JOIN staging.voice_intents i ON i.id=c.intent_id
WHERE i.account_sid=:account AND c.kind='vmhunter.claim'
AND NOT EXISTS(SELECT 1 FROM staging.voice_events r WHERE r.intent_id=c.intent_id
 AND r.kind='vmhunter.result' AND r.details->>'stream_stop_confirmed'='true')
AND NOT EXISTS(SELECT 1 FROM staging.voice_events r WHERE r.intent_id=c.intent_id
 AND r.kind='vmhunter.cleanup_verified' AND i.state IN ('finished','cancelled','expired')
 AND r.details->>'stream_stop_confirmed'='true'
 AND r.details->>'call_sid'=c.details->>'call_sid' AND r.details->>'nonce'=c.details->>'nonce'
 AND r.details->>'provider_status' IN ('completed','busy','no-answer','failed','canceled'))
AND (:include_recent OR c.created_at<clock_timestamp()-interval '20 seconds'
 OR EXISTS(SELECT 1 FROM staging.voice_events r WHERE r.intent_id=c.intent_id AND r.kind='vmhunter.result'))
ORDER BY c.id LIMIT 10"""
current = CLEANUP_LOOKUP_SQL + ' ORDER BY c.id LIMIT 10'
def inspect_query(sql, **params):
    with engine.connect() as db:
        query(db,'SET TRANSACTION READ ONLY')
        query(db,"SET LOCAL statement_timeout='1500ms'")
        return query(db,'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + sql, **params).scalar_one()[0]
def indexes(node):
    return ([node['Index Name']] if 'Index Name' in node else []) + [i for c in node.get('Plans',[]) for i in indexes(c)]
def summary(result):
    root=result['Plan']
    return dict(execution_ms=result['Execution Time'],
        shared_blocks=root.get('Shared Hit Blocks',0)+root.get('Shared Read Blocks',0),
        indexes=sorted(set(indexes(root))))
def snapshot():
    with engine.connect() as db:
        return tuple(query(db,"SELECT count(*),coalesce(sum(hashtextextended(row_to_json(t)::text,0)),0) FROM staging.voice_events t").one())
try:
    installer(migrator)
    # Bulk fixture setup uses the migration connection's existing 60s budget;
    # every evaluated runtime query retains the production 1.5-second limit.
    with migrator.begin() as db:
        query(db,"""INSERT INTO staging.voice_events(intent_id,kind,fingerprint,details)
          SELECT CAST(:intent AS uuid),'synthetic.non_vm',md5(n::text)||md5('event'||n::text),
             jsonb_build_object('synthetic',true)
          FROM generate_series(1,120000) n""",intent=fixture['first']['intent_id'])
        query(db,'ANALYZE staging.voice_events')
        query(db,'ANALYZE staging.voice_intents')
    params=dict(account=profile.account_sid,include_recent=False)
    before=snapshot()
    try:
        old=summary(inspect_query(legacy,**params))
    except Exception as error:
        code=getattr(getattr(error,'orig',None),'sqlstate',None)
        assert code=='57014', 'Unexpected baseline query failure'
        old={'statement_timeout':True,'sqlstate':code}
    new=summary(inspect_query(current,**params))
    assert 'voice_events_pkey' not in new['indexes'], 'Cleanup still scans broad journal primary key'
    assert new['execution_ms'] < 1500
    store=Store(engine,profile,pilot,provider_quota=ProviderQuota(100000))
    assert store.cleanup_candidates()==[]
    assert snapshot()==before, 'Read-only cleanup rewrote the journal'

    # Both queries must discover the same unconfirmed old claim, including
    # after the local call is terminal; terminal state alone is never proof.
    payload=fixture['call'](fixture['campaigns'][0],0)
    claimed=store.claim(payload)
    assert claimed
    fixture['finish'](claimed)
    for recent in (False,True):
        with engine.connect() as db:
            query(db,'SET TRANSACTION READ ONLY')
            query(db,"SET LOCAL statement_timeout='1500ms'")
            if recent:
                actual=[dict(r) for r in query(db,current,account=profile.account_sid,include_recent=True).mappings()]
                expected=[dict(r) for r in query(db,legacy,account=profile.account_sid,include_recent=True).mappings()]
                assert actual==expected and len(actual)==1
            else:
                assert store.cleanup_candidates()==[]
    assert store.cleanup_candidates(include_recent=True)==[claimed]
    assert store.verify_cleanup(claimed,'completed')
    assert store.cleanup_candidates(include_recent=True)==[]
    with engine.connect() as db:
        assert query(db,'SELECT version_num FROM staging.alembic_version').scalar_one()=='0012_incoming_runtime'
    print(json.dumps(dict(unrelated_events=120000,previous_period_claims=proof['history'],
        legacy=old,corrected=new,cleanup_semantics_preserved=True,no_broad_journal_scan=True,
        journal_unchanged_by_reads=True,schema='0012_incoming_runtime',real_calls=0)))
finally:
    migrator.dispose()
    engine.dispose()
