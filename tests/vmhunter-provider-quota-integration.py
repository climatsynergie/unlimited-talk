"""Disposable PG: previous-period volume cannot exhaust a new provider allowance."""
from dataclasses import replace
import json,runpy
from sqlalchemy import text
from app.identity.service import query
from app.telephony import vmhunter as vm,vmhunter_observer as module
from app.telephony.service import event

fixture=runpy.run_path('/tests/vmhunter-multicampaign-integration.py')
engine=fixture['engine'];profile=fixture['profile'];pilot=replace(fixture['pilot'],max_analyses=500)
call=fixture['call'];finish=fixture['finish'];campaigns=fixture['campaigns']
finish(fixture['five'])
with engine.begin() as db:
    then=query(db,"SELECT clock_timestamp()-interval '40 days'").scalar_one()
    query(db,"""WITH rows AS (
      SELECT gen_random_uuid() AS id FROM generate_series(1,5001)
    ), inserted AS (
      INSERT INTO staging.voice_intents(id,actor_id,session_hash,profile_hash,account_sid,application_sid,
        caller_number,destination,state,outcome,parent_call_sid,child_call_sid,expires_at,consumed_at,
        created_at,finished_at,campaign_id,contact_id,caller_number_id,dialer_generation,dialer_browser_id)
      SELECT r.id,i.actor_id,i.session_hash,i.profile_hash,i.account_sid,i.application_sid,
        i.caller_number,i.destination,'finished','completed','CA'||md5(r.id::text||'parent'),'CA'||md5(r.id::text),
        :then+interval '5 minutes',:then,:then,:then,i.campaign_id,i.contact_id,i.caller_number_id,
        i.dialer_generation,gen_random_uuid() FROM rows r CROSS JOIN staging.voice_intents i WHERE i.id=:old
      RETURNING id,child_call_sid
    ) INSERT INTO staging.voice_events(intent_id,kind,fingerprint,details,created_at)
      SELECT id,'vmhunter.claim',repeat('a',64),jsonb_build_object('pilot_id',CAST(:pilot AS text),
        'call_sid',child_call_sid,'nonce',md5(id::text)),:then FROM inserted
      UNION ALL
      SELECT id,'vmhunter.result',repeat('b',64),jsonb_build_object('pilot_id',CAST(:pilot AS text),
        'status','HUMAN','cause','HUMAN','action','continue','stream_stop_confirmed',true),:then FROM inserted""",
      then=then,old=fixture['first']['intent_id'],pilot=str(pilot.identifier))
with engine.connect() as db:
    history=query(db,"SELECT count(*) FROM staging.voice_events WHERE kind='vmhunter.claim'").scalar_one()
assert history>5000
one=call(campaigns[0],0)
assert module.Store(engine,profile,pilot).claim(one) is None,'Legacy fixed cap was unexpectedly removed'
quota_class=getattr(module,'ProviderQuota',None)
store=(module.Store(engine,profile,pilot,provider_quota=quota_class()) if quota_class else module.Store(engine,profile,pilot))
claim=store.claim(one)
assert claim is not None,'Historical test/month usage still imposes a 500/5000 lifetime ceiling'
# The subscription mode must not bypass scope, shared capacity or cleanup.
unselected=call(campaigns[2],2)
assert store.claim(unselected) is None;finish(unselected)
two=call(campaigns[1],1);two_claim=store.claim(two);assert two_claim is not None
three=call(campaigns[1],2)
assert store.claim(three) is None,'Subscription mode bypassed two-job capacity'
for value in (claim,two_claim):
    store.result(value,vm.Result('HUMAN','HUMAN'),stop_confirmed=True);finish(value)
third_claim=store.claim(three);assert third_claim is not None
store.result(third_claim,vm.Result('FAILED','stream_unavailable'),stop_confirmed=False)
four=call(campaigns[0],0)
assert store.claim(four) is None,'Subscription mode bypassed unresolved cleanup'
finish(third_claim)
with engine.begin() as db:
    event(db,third_claim['intent_id'],'vmhunter.cleanup_verified',dict(call_sid=third_claim['call_sid'],
        nonce=third_claim['nonce'],stream_stop_confirmed=True,provider_status='completed'))
fourth_claim=store.claim(four);assert fourth_claim is not None
store.result(fourth_claim,vm.Result('FAILED','LIMIT_REACHED'),stop_confirmed=True)
assert vm.screen_action(vm.Result('FAILED','LIMIT_REACHED'),stop_confirmed=True)=='continue'
finish(fourth_claim)
print(json.dumps(dict(previous_period_claims=history,free_monthly_allowance=5000,no_500_or_5000_lifetime_ceiling=True,
    old_fixed_canary_cap_preserved=True,scope_preserved=True,shared_capacity_preserved=True,
    cleanup_circuit_preserved=True,provider_limit_preserves_call=True,real_calls=0)))
engine.dispose()
