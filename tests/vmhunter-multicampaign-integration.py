"""Disposable PG: explicit campaigns share capacity, budget and cleanup safety."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from uuid import uuid4
from app.database import make_engine
from app.identity.service import query
from app.telephony import vmhunter as vm
from app.telephony.vmhunter_observer import Store
from app.telephony.service import profile_hash,event
from app.telephony.twilio_voice import ManualVoiceProfile

assert os.environ['DB_HOST']=='db' and os.environ.get('DB_DEPLOYMENT','local')=='local'
assert os.environ['COMMUNICATIONS_MODE']=='disabled'
engine=make_engine()
with engine.connect() as db:
    assert query(db,"SELECT value FROM staging.environment_metadata WHERE key='data_policy'").scalar_one()=='synthetic_only'
    assert query(db,'SELECT version_num FROM staging.alembic_version').scalar_one()=='0012_incoming_runtime'
actors=[uuid4() for _ in range(3)];campaigns=[vm.PILOT_CAMPAIGN,uuid4(),uuid4()]
contacts=[uuid4() for _ in actors];stages=[uuid4() for _ in campaigns]
numbers=['+14165550781','+14165550782','+14165550783'];number=uuid4()
profile=ManualVoiceProfile('AC'+uuid4().hex,'SK'+'b'*32,'c'*32,'AP'+'d'*32,
    'webhooks_sharedkey_'+'e'*26,'f'*32,'https://voice.example.invalid','+14165550100')
pilot=vm.Pilot.parse(dict(version=4,pilot_id=str(uuid4()),enabled=True,mode='screen',
    campaign_ids=[str(c) for c in campaigns[:2]],scope='campaign',agent_ids=[],test_numbers=[],
    max_analyses=3,audio_approved=True,screening_approved=True))
with engine.begin() as db:
    for i,actor in enumerate(actors):
        query(db,"INSERT INTO staging.identity_users(id,email,display_name,role,password_hash) VALUES (:id,:email,'Multi fixture','agent','unused')",id=actor,email=str(actor)+'@example.invalid')
        query(db,'INSERT INTO staging.contacts(id,phone) VALUES (:id,:phone)',id=contacts[i],phone=numbers[i])
    query(db,"INSERT INTO staging.voice_numbers(id,account_sid,provider_sid,number,name,country,voice_enabled,verified_at) VALUES (:id,:account,:sid,:phone,'Synthetic','CA',true,clock_timestamp())",id=number,account=profile.account_sid,sid='PN'+uuid4().hex,phone=profile.caller_number)
    for i,campaign in enumerate(campaigns):
        query(db,"INSERT INTO staging.campaigns(id,name,timezone,created_by) VALUES (:id,:name,'America/Toronto',:actor)",id=campaign,name='Synthetic '+str(i),actor=actors[0])
        query(db,"INSERT INTO staging.campaign_stages(id,campaign_id,name,kind,color,position) VALUES (:id,:campaign,'New','new','blue',0)",id=stages[i],campaign=campaign)
        for actor,contact in zip(actors,contacts):
            query(db,'INSERT INTO staging.campaign_agents(campaign_id,user_id,assigned_by) VALUES (:campaign,:actor,:actor)',campaign=campaign,actor=actor)
            query(db,'INSERT INTO staging.campaign_contacts(campaign_id,contact_id,stage_id) VALUES (:campaign,:contact,:stage)',campaign=campaign,contact=contact,stage=stages[i])

def call(campaign,index=0):
    identifier=uuid4();child='CA'+uuid4().hex
    with engine.begin() as db:
        query(db,"""INSERT INTO staging.voice_intents(id,actor_id,session_hash,profile_hash,account_sid,application_sid,
          caller_number,destination,state,parent_call_sid,child_call_sid,expires_at,consumed_at,campaign_id,
          contact_id,caller_number_id,dialer_generation,dialer_browser_id)
          VALUES (:id,:actor,:session,:hash,:account,:application,:caller,:destination,'authorized',:parent,:child,
          clock_timestamp()+interval '4 minutes',clock_timestamp(),:campaign,:contact,:number,1,:browser)""",
          id=identifier,actor=actors[index],session='1'*64,hash=profile_hash(profile),account=profile.account_sid,
          application=profile.twiml_app_sid,caller=profile.caller_number,destination=numbers[index],parent='CA'+uuid4().hex,
          child=child,campaign=campaign,contact=contacts[index],number=number,browser=uuid4())
        event(db,identifier,'vmhunter.screen',dict(pilot_id=str(pilot.identifier),mode='screen'))
        event(db,identifier,'vmhunter.screen.started',dict(call_sid=child))
    return dict(intent_id=str(identifier),call_sid=child,pilot_id=str(pilot.identifier))

def finish(payload):
    with engine.begin() as db:
        query(db,"UPDATE staging.voice_intents SET state='finished',outcome='completed',finished_at=clock_timestamp() WHERE id=:id",id=payload['intent_id'])

store=Store(engine,profile,pilot)
unselected=call(campaigns[2],2)
assert store.claim(unselected) is None
finish(unselected)
first=call(campaigns[0]);second=call(campaigns[1],1);third=call(campaigns[1],2)
with engine.begin() as db:
    query(db,'UPDATE staging.campaign_agents SET is_active=false WHERE campaign_id=:campaign AND user_id=:actor',campaign=campaigns[1],actor=actors[2])
assert store.claim(third) is None
with engine.begin() as db:
    query(db,'UPDATE staging.campaign_agents SET is_active=true WHERE campaign_id=:campaign AND user_id=:actor',campaign=campaigns[1],actor=actors[2])
with ThreadPoolExecutor(max_workers=2) as pool:
    duplicate=list(pool.map(store.claim,[first,first]))
assert sum(c is not None for c in duplicate)==1
one=next(c for c in duplicate if c is not None)
two=store.claim(second);assert two is not None
assert store.claim(third) is None,'Capacity must be global across selected campaigns'
for claimed in (one,two):
    store.result(claimed,vm.Result('HUMAN','HUMAN'),stop_confirmed=True)
    finish(claimed)
three=store.claim(third);assert three is not None
store.result(three,vm.Result('HUMAN','HUMAN'),stop_confirmed=True)
finish(three)
fourth=call(campaigns[1],2)
assert store.claim(fourth) is None,'Total budget reset at a campaign boundary'
removed=Store(engine,profile,replace(pilot,campaigns=frozenset({campaigns[1]})))
assert removed.claim(fourth) is None,'Removing a campaign must not refund spent budget'
expanded=Store(engine,profile,replace(pilot,max_analyses=5))
four=expanded.claim(fourth);assert four is not None
expanded.result(four,vm.Result('FAILED','stream_unavailable'),stop_confirmed=False)
fifth=call(campaigns[0],1)
assert expanded.claim(fifth) is None,'An unresolved stream on campaign B must block campaign A'
with engine.begin() as db:
    query(db,"UPDATE staging.voice_intents SET state='finished',outcome='completed',finished_at=clock_timestamp() WHERE id=:id",id=four['intent_id'])
    event(db,four['intent_id'],'vmhunter.cleanup_verified',dict(call_sid=four['call_sid'],nonce=four['nonce'],stream_stop_confirmed=True,provider_status='completed'))
five=expanded.claim(fifth);assert five is not None
expanded.result(five,vm.Result('HUMAN','HUMAN'),stop_confirmed=True)
with engine.connect() as db:
    assert query(db,"SELECT count(*) FROM staging.voice_events WHERE kind='vmhunter.claim'").scalar_one()==5
    assert query(db,'SELECT version_num FROM staging.alembic_version').scalar_one()=='0012_incoming_runtime'
print(json.dumps(dict(explicit_campaigns=True,all_assigned_agents=True,unselected_campaign_denied=True,
    removed_assignment_denied=True,duplicate_concurrent_claims_safe=True,shared_capacity=True,
    shared_budget=True,removed_campaign_cannot_reset_budget=True,shared_cleanup_circuit=True,
    schema='0012_incoming_runtime',migration_required=False,real_calls=0)))
engine.dispose()
