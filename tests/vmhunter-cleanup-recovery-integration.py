"""Disposable schema12: interrupted cleanup automatically recovers, with bound proof."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json,runpy
from app.identity.service import query
from app.telephony import vmhunter as vm
from app.telephony.vmhunter_observer import Store,ProviderQuota
fixture=runpy.run_path('/tests/vmhunter-multicampaign-integration.py')
engine=fixture['engine'];profile=fixture['profile'];pilot=fixture['pilot']
call=fixture['call'];finish=fixture['finish'];campaigns=fixture['campaigns']
finish(fixture['five'])
store=Store(engine,profile,pilot,provider_quota=ProviderQuota())
one=call(campaigns[0],0);claimed=store.claim(one);assert claimed
store.result(claimed,vm.Result('FAILED','stream_unavailable'),stop_confirmed=False)
two=call(campaigns[1],1)
assert store.claim(two) is None,'The unverified live stream must still block analysis'
assert store.cleanup_candidates()==[claimed]
# Even a terminal provider read cannot override a still-live DB call.
assert not store.verify_cleanup(claimed,'completed')
for status in ('in-progress','ringing','unknown',None,[],True):
 assert not store.verify_cleanup(claimed,status)
finish(claimed)
for change in ({'nonce':'0'*32},{'call_sid':'CA'+'0'*32},{'pilot_id':'00000000-0000-0000-0000-000000000000'}):
 assert not store.verify_cleanup(claimed|change,'completed')
from dataclasses import replace
foreign=Store(engine,replace(profile,account_sid='AC'+'0'*32),pilot,provider_quota=ProviderQuota())
assert foreign.cleanup_candidates()==[]
assert not foreign.verify_cleanup(claimed,'completed')
with engine.connect() as db:
 before=[tuple(x) for x in query(db,'SELECT id,state,outcome,finished_at FROM staging.voice_intents ORDER BY id')]
 original=query(db,"SELECT details FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.result'",id=claimed['intent_id']).scalar_one()
# Competing supervisors append one idempotent proof, without rewriting results.
with ThreadPoolExecutor(max_workers=2) as pool:
 assert all(pool.map(lambda _:store.verify_cleanup(claimed,'completed'),range(2)))
assert store.cleanup_candidates()==[]
next_claim=store.claim(two);assert next_claim,'Verified late cleanup did not restore analysis'
store.result(next_claim,vm.Result('MACHINE','INITIALSILENCE'),stop_confirmed=True,audio_stats=dict(pcm_bytes=320,frames=1,signal_frames=0))
assert vm.screen_action(vm.Result('MACHINE','INITIALSILENCE'),stop_confirmed=True)=='continue'
with engine.connect() as db:
 assert [tuple(x) for x in query(db,'SELECT id,state,outcome,finished_at FROM staging.voice_intents ORDER BY id')]==before
 assert query(db,"SELECT details FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.result'",id=claimed['intent_id']).scalar_one()==original
 assert query(db,"SELECT count(*) FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.cleanup_verified'",id=claimed['intent_id']).scalar_one()==1
 assert query(db,"SELECT details->'audio_stats' FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.result'",id=next_claim['intent_id']).scalar_one()==dict(pcm_bytes=320,frames=1,signal_frames=0)
 assert query(db,'SELECT version_num FROM staging.alembic_version').scalar_one()=='0012_incoming_runtime'
finish(next_claim)
# Lost result writes must not allow a recent unconfirmed claim to disappear
# during its 20-second lease. Healthy in-flight jobs remain outside discovery.
recent=call(campaigns[0],0);recent_claim=store.claim(recent);assert recent_claim
assert store.cleanup_candidates()==[]
assert store.cleanup_candidates(include_recent=True)==[recent_claim]
assert not store.verify_cleanup(recent_claim,'completed')
finish(recent_claim)
assert store.verify_cleanup(recent_claim,'completed')
assert store.cleanup_candidates(include_recent=True)==[]
print(json.dumps(dict(late_terminal_recovery=True,live_call_protected=True,nonce_call_pilot_account_binding=True,concurrent_recovery_idempotent=True,history_unchanged=True,initialsilence_continues=True,schema='0012_incoming_runtime',migration_required=False,real_calls=0)))
engine.dispose()
