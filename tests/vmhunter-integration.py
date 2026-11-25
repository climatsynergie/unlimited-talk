"""Disposable PostgreSQL proof: exact schema12, competing claims and rollback."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
import time
from uuid import uuid4

from sqlalchemy import text
from app.database import make_engine
from app.identity.service import query
from app.telephony import vmhunter as vm
from app.telephony.vmhunter_observer import Store
from app.telephony.service import profile_hash, event
from app.telephony.twilio_voice import ManualVoiceProfile

assert os.environ.get('DB_HOST') == 'db'
assert os.environ.get('DB_DEPLOYMENT', 'local') == 'local'
assert os.environ.get('COMMUNICATIONS_MODE') == 'disabled'
engine = make_engine()
with engine.connect() as db:
    assert query(db,"SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one()=='synthetic_only'
    assert query(db,'SELECT version_num FROM staging.alembic_version').scalar_one()=='0012_incoming_runtime'

actors=[uuid4(),uuid4()];number_id=uuid4();stage=uuid4()
profile=ManualVoiceProfile('AC'+uuid4().hex,'SK'+'b'*32,'c'*32,'AP'+'d'*32,
    'webhooks_sharedkey_'+'e'*26,'f'*32,'https://voice.example.invalid','+14165550100')
numbers=['+14165550911','+14165550912']
pilot=vm.Pilot(uuid4(),True,frozenset(actors),2,frozenset(numbers),True)
store=Store(engine,profile,pilot)
intents=[]
with engine.begin() as db:
    for actor in actors:
        query(db,"INSERT INTO staging.identity_users(id,email,display_name,role,password_hash) VALUES (:id,:email,'VM synthetic','agent','unused')",
            id=actor,email=str(actor)+'@example.invalid')
    query(db,"INSERT INTO staging.campaigns(id,name,timezone,created_by) VALUES (:id,'VM synthetic pilot','America/Toronto',:actor)",
        id=vm.PILOT_CAMPAIGN,actor=actors[0])
    query(db,"INSERT INTO staging.campaign_stages(id,campaign_id,name,kind,color,position) VALUES (:id,:campaign,'Synthetic','new','blue',0)",
        id=stage,campaign=vm.PILOT_CAMPAIGN)
    query(db,"INSERT INTO staging.voice_numbers(id,account_sid,provider_sid,number,name,country,voice_enabled,verified_at) VALUES (:id,:account,:sid,:number,'Synthetic','CA',true,clock_timestamp())",
        id=number_id,account=profile.account_sid,sid='PN'+uuid4().hex,number=profile.caller_number)
    for actor,number in zip(actors,numbers):
        query(db,'INSERT INTO staging.campaign_agents(campaign_id,user_id,assigned_by) VALUES (:campaign,:actor,:actor)',
            campaign=vm.PILOT_CAMPAIGN,actor=actor)
        contact=uuid4();identifier=uuid4();child='CA'+uuid4().hex
        query(db,'INSERT INTO staging.contacts(id,phone) VALUES (:id,:phone)',id=contact,phone=number)
        query(db,'INSERT INTO staging.campaign_contacts(campaign_id,contact_id,stage_id) VALUES (:campaign,:contact,:stage)',
            campaign=vm.PILOT_CAMPAIGN,contact=contact,stage=stage)
        query(db,"""INSERT INTO staging.voice_intents(id,actor_id,session_hash,profile_hash,account_sid,
            application_sid,caller_number,destination,state,parent_call_sid,child_call_sid,expires_at,consumed_at,
            campaign_id,contact_id,caller_number_id,dialer_generation,dialer_browser_id)
            VALUES (:id,:actor,:session,:hash,:account,:application,:caller,:destination,'answered',:parent,:child,
                clock_timestamp()+interval '4 minutes',clock_timestamp(),:campaign,:contact,:number,1,:browser)""",
            id=identifier,actor=actor,session='1'*64,hash=profile_hash(profile),account=profile.account_sid,
            application=profile.twiml_app_sid,caller=profile.caller_number,destination=number,parent='CA'+uuid4().hex,
            child=child,campaign=vm.PILOT_CAMPAIGN,contact=contact,number=number_id,browser=uuid4())
        intents.append(dict(intent_id=str(identifier),call_sid=child,pilot_id=str(pilot.identifier)))

def facts():
    with engine.connect() as db:
        return [tuple(row) for row in query(db,'SELECT id,state,outcome,membership_version,settled_at FROM staging.voice_intents WHERE campaign_id=:campaign ORDER BY id',campaign=vm.PILOT_CAMPAIGN)], \
            [tuple(row) for row in query(db,'SELECT campaign_id,contact_id,stage_id,version FROM staging.campaign_contacts WHERE campaign_id=:campaign ORDER BY contact_id',campaign=vm.PILOT_CAMPAIGN)]

before=facts()
# Exact ownership, active assignment, automatic-only scope and caller state.
for changed in [dict(call_sid='CA'+'0'*32),dict(pilot_id=str(uuid4()))]:
    assert store.claim(intents[0]|changed) is None
assert Store(engine,profile,replace(pilot,enabled=False)).claim(intents[0]) is None
assert Store(engine,profile,replace(pilot,agents=frozenset())).claim(intents[0]) is None
assert Store(engine,profile,replace(pilot,test_numbers=frozenset())).claim(intents[0]) is None

with engine.begin() as db:
    query(db,'UPDATE staging.campaign_agents SET is_active=false WHERE user_id=:id',id=actors[0])
assert store.claim(intents[0]) is None
with engine.begin() as db:
    query(db,'UPDATE staging.campaign_agents SET is_active=true WHERE user_id=:id',id=actors[0])

# Actual concurrent PG transactions must grant only one provider analysis.
with ThreadPoolExecutor(max_workers=2) as pool:
    claims=list(pool.map(store.claim,[intents[0],intents[0]]))
assert sum(item is not None for item in claims)==1
first=next(item for item in claims if item is not None)
second=store.claim(intents[1]);assert second is not None
store.result(first,vm.Result('MACHINE','INITIALSILENCE'),stop_confirmed=True)
store.result(first,vm.Result('MACHINE','MACHINE_BEEP'),stop_confirmed=True)
store.result(second,vm.Result('FAILED','LIMIT_REACHED'),stop_confirmed=True)
assert facts()==before,'Observation mutated phone/pipeline facts'

with engine.connect() as db:
    assert query(db,"SELECT count(*) FROM staging.voice_events WHERE kind='vmhunter.claim'").scalar_one()==2
    assert query(db,"SELECT count(*) FROM staging.voice_events WHERE kind='vmhunter.result'").scalar_one()==2
    result=query(db,"SELECT details FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.result'",id=first['intent_id']).scalar_one()
    assert result['cause']=='INITIALSILENCE' and result['action']=='continue'
    assert query(db,'SELECT version_num FROM staging.alembic_version').scalar_one()=='0012_incoming_runtime'

# A third eligible call cannot exceed a two-analysis budget, even after the
# first two have finished. This is distinct from replay/idempotency checks.
third=uuid4();third_child='CA'+uuid4().hex
with engine.begin() as db:
    query(db,"UPDATE staging.voice_intents SET state='finished',outcome='completed',finished_at=clock_timestamp() WHERE id=:id",
          id=first['intent_id'])
    query(db,"""INSERT INTO staging.voice_intents(id,actor_id,session_hash,profile_hash,account_sid,
        application_sid,caller_number,destination,state,parent_call_sid,child_call_sid,expires_at,consumed_at,
        campaign_id,contact_id,caller_number_id,dialer_generation,dialer_browser_id)
        SELECT :id,actor_id,session_hash,profile_hash,account_sid,application_sid,caller_number,destination,
            'answered',:parent,:child,clock_timestamp()+interval '4 minutes',clock_timestamp(),
            campaign_id,contact_id,caller_number_id,dialer_generation,:browser FROM staging.voice_intents WHERE id=:old""",
        id=third,parent='CA'+uuid4().hex,child=third_child,browser=uuid4(),old=first['intent_id'])
third_payload=dict(intent_id=str(third),call_sid=third_child,pilot_id=str(pilot.identifier))
assert store.claim(third_payload) is None
expanded=Store(engine,profile,replace(pilot,max_analyses=3))
third_claim=expanded.claim(third_payload);assert third_claim is not None
# A new process/store must not reset an unconfirmed-stop circuit. Simulate the
# next eligible call with an expanded budget so only the circuit can reject it.
fourth=uuid4();fourth_child='CA'+uuid4().hex
with engine.begin() as db:
    query(db,"UPDATE staging.voice_intents SET state='finished',outcome='completed',finished_at=clock_timestamp() WHERE id=:id",id=third)
    query(db,"""INSERT INTO staging.voice_intents(id,actor_id,session_hash,profile_hash,account_sid,
        application_sid,caller_number,destination,state,parent_call_sid,child_call_sid,expires_at,consumed_at,
        campaign_id,contact_id,caller_number_id,dialer_generation,dialer_browser_id)
        SELECT :id,actor_id,session_hash,profile_hash,account_sid,application_sid,caller_number,destination,
            'answered',:parent,:child,clock_timestamp()+interval '4 minutes',clock_timestamp(),
            campaign_id,contact_id,caller_number_id,dialer_generation,:browser FROM staging.voice_intents WHERE id=:old""",
        id=fourth,parent='CA'+uuid4().hex,child=fourth_child,browser=uuid4(),old=third)
restarted=Store(engine,profile,replace(pilot,max_analyses=4))
# Let the actual DB lease window expire instead of bypassing append-only event
# permissions or weakening the production timeout in order to test recovery.
time.sleep(20.1)
assert restarted.claim(dict(intent_id=str(fourth),call_sid=fourth_child,pilot_id=str(pilot.identifier))) is None
expanded.result(third_claim,vm.Result('FAILED','stream_unavailable'),stop_confirmed=False)
assert restarted.claim(dict(intent_id=str(fourth),call_sid=fourth_child,pilot_id=str(pilot.identifier))) is None
# Recovery appends verified evidence; it never edits the failed historical result.
with engine.begin() as db:
    event(db,third,'vmhunter.cleanup_verified',dict(call_sid=third_child,
        nonce='0'*32,stream_stop_confirmed=True,provider_status='completed'))
assert restarted.claim(dict(intent_id=str(fourth),call_sid=fourth_child,pilot_id=str(pilot.identifier))) is None
with engine.begin() as db:
    event(db,third,'vmhunter.cleanup_verified',dict(call_sid=third_child,
        nonce=third_claim['nonce'],stream_stop_confirmed=True,provider_status='completed'))
fourth_claim=restarted.claim(dict(intent_id=str(fourth),call_sid=fourth_child,pilot_id=str(pilot.identifier)))
assert fourth_claim is not None,'Verified terminal-call cleanup did not recover the circuit'
restarted.result(fourth_claim,vm.Result('HUMAN','HUMAN'),stop_confirmed=True)
# Leave no active synthetic calls for the surrounding API regression suite.
with engine.begin() as db:
    query(db,"UPDATE staging.voice_intents SET state='finished',outcome='completed',finished_at=coalesce(finished_at,clock_timestamp()) WHERE campaign_id=:campaign",
        campaign=vm.PILOT_CAMPAIGN)

# Existing append-only history works without a new schema; code rollback needs
# no destructive migration. Verify predecessor imports/reads in a separate proof.
print(json.dumps({'schema':'0012_incoming_runtime','competing_claims':2,'granted_claims':1,
    'idempotent_results':True,'scoped_assignment':True,'phone_and_pipeline_facts_unchanged':True,'analysis_budget_enforced':True,
    'migration_required':False,'stale_claim_circuit_survives_restart':True,
    'stop_failure_circuit_survives_restart':True,'external_calls':0}))
engine.dispose()
