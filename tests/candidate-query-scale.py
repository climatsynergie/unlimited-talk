"""Actual candidate SQL on an explicitly disposable, network-isolated PG cluster.

Run from a dependency image with current backend/app mounted read-only. This
is a query/scale regression, not a PSTN test or complete reservation race proof.
"""
from itertools import chain, islice
import json
import os
import importlib.util
import time
from uuid import UUID
from sqlalchemy import create_engine, text
from app.telephony.dialer_service import candidates

if os.environ.get('CANDIDATE_BASELINE_FILE'):
    spec=importlib.util.spec_from_file_location('candidate_baseline',os.environ['CANDIDATE_BASELINE_FILE'])
    baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
    candidates=baseline.candidates

engine=create_engine('postgresql+psycopg://postgres@127.0.0.1/postgres',pool_size=1,max_overflow=0)
with engine.connect() as db:
    assert db.execute(text('SHOW cluster_name')).scalar_one()=='ut-candidate-scale-qa', 'Disposable cluster required'
# Every resource in this cluster is synthetic and belongs to this one proof.
with engine.begin() as db:
    db.exec_driver_sql('''DROP SCHEMA IF EXISTS staging CASCADE; CREATE SCHEMA staging;
    CREATE TABLE staging.contacts(id uuid PRIMARY KEY,phone text UNIQUE NOT NULL,profile jsonb NOT NULL DEFAULT '{}',do_not_contact boolean NOT NULL DEFAULT false,non_interested boolean NOT NULL DEFAULT false);
    CREATE TABLE staging.campaigns(id uuid PRIMARY KEY,timezone text NOT NULL,is_active boolean NOT NULL DEFAULT true);
    CREATE TABLE staging.campaign_stages(id uuid PRIMARY KEY,campaign_id uuid NOT NULL,kind text NOT NULL,is_active boolean NOT NULL DEFAULT true);
    CREATE TABLE staging.campaign_contacts(campaign_id uuid NOT NULL,contact_id uuid NOT NULL,stage_id uuid NOT NULL,queue_position bigint NOT NULL,is_active boolean NOT NULL DEFAULT true,PRIMARY KEY(campaign_id,contact_id));
    CREATE INDEX campaign_contacts_column ON staging.campaign_contacts(campaign_id,stage_id,queue_position) WHERE is_active;
    CREATE INDEX campaign_contacts_contact ON staging.campaign_contacts(contact_id,campaign_id) WHERE is_active;
    CREATE INDEX candidate_queue_diagnostic ON staging.campaign_contacts(campaign_id,queue_position,contact_id) WHERE is_active;
    CREATE TABLE staging.campaign_agents(campaign_id uuid,user_id uuid,is_active boolean DEFAULT true,PRIMARY KEY(campaign_id,user_id));
    CREATE INDEX campaign_agents_user ON staging.campaign_agents(user_id,campaign_id) WHERE is_active;
    CREATE TABLE staging.voice_campaign_settings(campaign_id uuid PRIMARY KEY,enabled boolean DEFAULT true);
    CREATE TABLE staging.campaign_events(id bigint PRIMARY KEY,campaign_id uuid,contact_id uuid,action text,details jsonb DEFAULT '{}');
    CREATE INDEX campaign_events_contact ON staging.campaign_events(campaign_id,contact_id,id DESC);
    CREATE TABLE staging.appointments(contact_id uuid,status text,ends_at timestamptz);
    CREATE INDEX appointments_contact ON staging.appointments(contact_id,ends_at);
    CREATE TABLE staging.callbacks(id uuid PRIMARY KEY,campaign_id uuid,contact_id uuid,owner_id uuid,status text,due_at timestamptz,version integer DEFAULT 0);
    CREATE UNIQUE INDEX callbacks_one_pending_contact ON staging.callbacks(contact_id) WHERE status='scheduled';
    CREATE INDEX callbacks_owner_due ON staging.callbacks(owner_id,due_at,id) WHERE status='scheduled';
    CREATE TABLE staging.voice_intents(id uuid PRIMARY KEY,account_sid text,destination text,state text,expires_at timestamptz,consumed_at timestamptz,created_at timestamptz,attempt_timezone text,callback_id uuid,callback_version integer);
    CREATE INDEX voice_attempt_day ON staging.voice_intents(account_sid,destination,consumed_at) WHERE consumed_at IS NOT NULL;
    CREATE INDEX voice_destination_timezone ON staging.voice_intents(account_sid,destination,created_at,id);
    CREATE UNIQUE INDEX voice_one_active_destination ON staging.voice_intents(account_sid,destination) WHERE state IN ('reserved','authorized','ringing','answered');
    INSERT INTO staging.contacts(id,phone) SELECT md5('contact'||i)::uuid,'+1416'||lpad(i::text,7,'0') FROM generate_series(1,106000)i;
    INSERT INTO staging.campaigns(id,timezone) SELECT md5('campaign'||i)::uuid,'America/Toronto' FROM generate_series(1,3)i;
    INSERT INTO staging.campaign_stages(id,campaign_id,kind) SELECT md5('stage'||c||'-'||s)::uuid,md5('campaign'||c)::uuid,(ARRAY['new','no_answer','other','custom'])[s] FROM generate_series(1,3)c CROSS JOIN generate_series(1,4)s;
    INSERT INTO staging.campaign_contacts(campaign_id,contact_id,stage_id,queue_position) SELECT md5('campaign1')::uuid,md5('contact'||i)::uuid,md5('stage1-'||(1+mod(i,4)))::uuid,i FROM generate_series(1,40000)i;
    INSERT INTO staging.campaign_contacts(campaign_id,contact_id,stage_id,queue_position) SELECT md5('campaign2')::uuid,md5('contact'||i)::uuid,md5('stage2-'||(1+mod(i,4)))::uuid,i FROM generate_series(1,60000)i;
    INSERT INTO staging.campaign_contacts(campaign_id,contact_id,stage_id,queue_position) SELECT md5('campaign3')::uuid,md5('contact'||i)::uuid,md5('stage3-'||(1+mod(i,4)))::uuid,i FROM generate_series(58001,106000)i;
    INSERT INTO staging.voice_campaign_settings(campaign_id) SELECT id FROM staging.campaigns;
    INSERT INTO staging.campaign_events(id,campaign_id,contact_id,action) SELECT i,md5('campaign'||(1+mod(i,3)))::uuid,md5('contact'||(1+mod(i,106000)))::uuid,'call.finished' FROM generate_series(1,152000)i;
    INSERT INTO staging.campaign_events(id,campaign_id,action,details) SELECT 152000+i,md5('campaign'||i)::uuid,'calling.settings_changed','{"after":{"policy":{"attempts_per_day":2,"retry_minutes":120}}}' FROM generate_series(1,3)i;
    INSERT INTO staging.voice_intents(id,account_sid,destination,state,consumed_at,created_at,attempt_timezone)
      SELECT md5('intent'||i)::uuid,'ACaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','+1416'||lpad(i::text,7,'0'),'finished',clock_timestamp()-interval '2 days',clock_timestamp()-interval '2 days','America/Toronto' FROM generate_series(1,1850)i;
    ANALYZE staging.contacts; ANALYZE staging.campaign_contacts; ANALYZE staging.campaigns; ANALYZE staging.campaign_stages; ANALYZE staging.campaign_events; ANALYZE staging.voice_intents; ANALYZE staging.callbacks; ANALYZE staging.appointments;
    ''')
values={'actor':UUID('00000000-0000-0000-0000-000000000001'),'admin':True,'account':'AC'+'a'*32}
with engine.connect() as db:
    campaign=db.execute(text("SELECT md5('campaign1')::uuid")).scalar_one()
    db.execute(text("SET statement_timeout='3s'"))
    started=time.monotonic()
    result=list(islice(candidates(db,values,campaign),100))
    elapsed=time.monotonic()-started
    assert len(result)==100 and [r['candidate_order'] for r in result]==list(range(1,101))
    print(json.dumps({'case':'scale_first_100','contacts':106000,'memberships':148000,'selected':40000,'events':152003,'intents':1850,'seconds':elapsed,'rows':len(result),'statement_timeout_ms':3000}),flush=True)
    assert elapsed<1.0, 'First100 must retain >=2s headroom under the production3s statement timeout'
with engine.begin() as db:
    db.execute(text("UPDATE staging.contacts SET do_not_contact=true WHERE id IN (SELECT md5('contact'||i)::uuid FROM generate_series(1,250)i)"))
    db.execute(text("UPDATE staging.voice_intents SET consumed_at=clock_timestamp() WHERE destination IN ('+14160000251','+14160000252')"))
    db.execute(text("INSERT INTO staging.callbacks(id,campaign_id,contact_id,owner_id,status,due_at) VALUES (md5('callback')::uuid,md5('campaign2')::uuid,md5('contact1001')::uuid,:actor,'scheduled',clock_timestamp()-interval '1 minute')"),values)
with engine.connect() as db:
    db.execute(text("SET statement_timeout='3s'"))
    started=time.monotonic()
    normal=list(islice(candidates(db,values,campaign),1))
    assert normal[0]['candidate_order']==253,normal
    ordered=list(islice(chain(candidates(db,values),candidates(db,values,campaign)),1))
    assert ordered[0]['campaign_id']!=campaign and ordered[0]['candidate_order']!=253
    print(json.dumps({'case':'skip_two_entire_raw_pages_and_cooldown_then_callback_priority','seconds':time.monotonic()-started,'first_ordinary_position':normal[0]['candidate_order'],'callback_first':True}),flush=True)
with engine.connect() as db:
    # Mirror next_call's transaction-local tuning and prove a fully rejected
    # campaign terminates instead of looping on a rejected raw page.
    db.execute(text('SET LOCAL jit=off'))
    db.execute(text("SET LOCAL statement_timeout='3s'"))
    db.execute(text('UPDATE staging.contacts SET do_not_contact=true WHERE id IN (SELECT contact_id FROM staging.campaign_contacts WHERE campaign_id=:c)'),{'c':campaign})
    started=time.monotonic()
    empty=list(candidates(db,values,campaign))
    elapsed=time.monotonic()-started
    assert not empty
    assert elapsed<5.0,'Exhausting an entirely ineligible synthetic campaign must remain bounded'
    print(json.dumps({'case':'all40000_selected_contacts_ineligible','seconds':elapsed,'rows':0}),flush=True)
    db.rollback()
engine.dispose()
