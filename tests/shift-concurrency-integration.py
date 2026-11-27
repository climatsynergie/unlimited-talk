"""Disposable PG reproduction: agent voicemail and signed screening compete.

The user transaction owns the authenticated actor lock. The competing callback
must wait before taking the intent, rather than retain it while audit's foreign
key waits for that actor. No external request or real phone call is made.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime,timezone
import json
import runpy
import threading
import time
from unittest.mock import patch
from uuid import UUID

from app.database import make_engine
from app.identity.service import query
from app.telephony import service,vmhunter as vm,vmhunter_screen as screen
from app.telephony.vmhunter_observer import Store,ProviderQuota

fixture=runpy.run_path('/tests/vmhunter-multicampaign-integration.py')
engine=fixture['engine'];profile=fixture['profile'];pilot=fixture['pilot']
fixture['finish'](fixture['five'])
payload=fixture['call'](fixture['campaigns'][0],0)
store=Store(engine,profile,pilot,provider_quota=ProviderQuota())
claim=store.claim(payload);assert claim
store.result(claim,vm.Result('MACHINE','MACHINE'),stop_confirmed=True)
identifier=UUID(payload['intent_id']);actor_id=fixture['actors'][0]
with engine.connect() as db:
    parent=query(db,'SELECT parent_call_sid FROM staging.voice_intents WHERE id=:id',id=identifier).scalar_one()
params=dict(CallSid=payload['call_sid'],ParentCallSid=parent)
callback_engine=make_engine();ready=threading.Event();pids=[]

class BoundEngine:
    def __init__(self,db):self.db=db
    @contextmanager
    def begin(self):yield self.db

def callback():
    with callback_engine.begin() as db:
        query(db,"SET LOCAL statement_timeout='6500ms'")
        pids.append(query(db,'SELECT pg_backend_pid()').scalar_one());ready.set()
        return screen.complete(BoundEngine(db),profile,identifier,params)

errors=[];response=None;human=None
with ThreadPoolExecutor(max_workers=1) as pool,patch.object(screen,'configured',return_value=pilot):
    try:
        with engine.begin() as human_db:
            query(human_db,"SET LOCAL statement_timeout='6500ms'")
            query(human_db,'SELECT id FROM staging.identity_users WHERE id=:id FOR UPDATE',id=actor_id)
            future=pool.submit(callback)
            assert ready.wait(2),'Callback did not start'
            # Both old and repaired paths block on the actor. The old path
            # already owns the intent; the repaired path must not own it yet.
            blocked=False
            until=time.monotonic()+2
            while time.monotonic()<until:
                with engine.connect() as observer:
                    blocked=query(observer,"SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=:pid",pid=pids[0]).scalar_one()
                if blocked:break
                time.sleep(0.01)
            assert blocked,'The intended concurrency schedule was not established'
            human=service.voicemail(human_db,dict(id=actor_id,session_hash='1'*64),identifier)
    except Exception as error:
        errors.append(dict(side='human',type=type(error).__name__,sqlstate=getattr(getattr(error,'orig',None),'sqlstate',None)))
    try:response=future.result(timeout=8)
    except Exception as error:
        errors.append(dict(side='callback',type=type(error).__name__,sqlstate=getattr(getattr(error,'orig',None),'sqlstate',None)))
print(json.dumps(dict(concurrent_errors=errors,human_completed=bool(human),callback_completed=bool(response))),flush=True)
assert not errors,'Concurrent voicemail/screening transactions failed: '+str(errors)
assert human['disposition']=='voicemail' and 'Hangup' in response
with engine.connect() as db:
    assert query(db,"SELECT count(*) FROM staging.voice_events WHERE intent_id=:id AND kind='disposition.voicemail'",id=identifier).scalar_one()==1
    assert query(db,"SELECT details->>'action' FROM staging.voice_events WHERE intent_id=:id AND kind='vmhunter.screen.decision'",id=identifier).scalar_one()=='hangup'
    assert query(db,'SELECT version_num FROM staging.alembic_version').scalar_one()=='0012_incoming_runtime'
fixture['finish'](payload)
engine.dispose();callback_engine.dispose()
print(json.dumps(dict(voicemail_callback_concurrency=True,idempotent_disposition=True,schema_unchanged=True,external_calls=0)),flush=True)
