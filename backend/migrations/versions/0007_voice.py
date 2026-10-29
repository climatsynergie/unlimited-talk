"""Durable controlled-call reservations and append-only provider history."""
from alembic import op
revision = '0007_voice'
down_revision = '0006_callbacks'
branch_labels = depends_on = None


def upgrade():
    op.execute(r'''
    CREATE TABLE staging.voice_intents (
        id uuid PRIMARY KEY,
        actor_id uuid NOT NULL REFERENCES staging.identity_users(id),
        -- Deliberately not a FK: deleting a revoked session must preserve calls.
        session_hash text NOT NULL CHECK(length(session_hash)=64),
        profile_hash text NOT NULL CHECK(length(profile_hash)=64),
        account_sid text NOT NULL CHECK(account_sid ~ '^AC[0-9a-fA-F]{32}$'),
        application_sid text NOT NULL CHECK(application_sid ~ '^AP[0-9a-fA-F]{32}$'),
        caller_number text NOT NULL CHECK(caller_number ~ '^\+[1-9][0-9]{8,14}$'),
        destination text NOT NULL CHECK(destination ~ '^\+[1-9][0-9]{8,14}$' AND destination<>caller_number),
        state text NOT NULL DEFAULT 'reserved' CHECK(state IN ('reserved','authorized','ringing','answered','finished','cancelled','expired')),
        parent_call_sid text UNIQUE CHECK(parent_call_sid ~ '^CA[0-9a-fA-F]{32}$'),
        child_call_sid text UNIQUE CHECK(child_call_sid ~ '^CA[0-9a-fA-F]{32}$' AND child_call_sid<>parent_call_sid),
        last_child_sequence integer NOT NULL DEFAULT -1 CHECK(last_child_sequence>=-1),
        outcome text CHECK(outcome IN ('completed','busy','no-answer','failed','canceled')),
        outcome_rank integer NOT NULL DEFAULT 0 CHECK(outcome_rank BETWEEN 0 AND 3),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        expires_at timestamptz NOT NULL CHECK(expires_at>created_at AND expires_at<=created_at+interval '5 minutes'),
        consumed_at timestamptz,
        finished_at timestamptz,
        CHECK((state='reserved' AND consumed_at IS NULL) OR state<>'reserved'),
        CHECK((state IN ('authorized','ringing','answered','finished') AND consumed_at IS NOT NULL AND parent_call_sid IS NOT NULL)
              OR state NOT IN ('authorized','ringing','answered','finished'))
    );
    CREATE UNIQUE INDEX voice_one_active_actor ON staging.voice_intents(actor_id)
        WHERE state IN ('reserved','authorized','ringing','answered');
    CREATE UNIQUE INDEX voice_one_active_destination ON staging.voice_intents(account_sid,destination)
        WHERE state IN ('reserved','authorized','ringing','answered');
    CREATE INDEX voice_actor_history ON staging.voice_intents(actor_id,created_at DESC,id);
    CREATE TABLE staging.voice_events (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        intent_id uuid NOT NULL REFERENCES staging.voice_intents(id),
        kind text NOT NULL,
        fingerprint text NOT NULL CHECK(length(fingerprint)=64),
        details jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        UNIQUE(intent_id,kind,fingerprint)
    );
    CREATE INDEX voice_event_history ON staging.voice_events(intent_id,id DESC);
    CREATE TABLE staging.voice_recordings (
        sid text PRIMARY KEY CHECK(sid ~ '^RE[0-9a-fA-F]{32}$'),
        intent_id uuid NOT NULL REFERENCES staging.voice_intents(id),
        call_sid text NOT NULL CHECK(call_sid ~ '^CA[0-9a-fA-F]{32}$'),
        duration integer NOT NULL CHECK(duration BETWEEN 0 AND 600),
        channels integer NOT NULL CHECK(channels=2),
        state text NOT NULL DEFAULT 'pending_archive' CHECK(state IN ('pending_archive','archived')),
        object_key text,
        checksum text,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CHECK(state<>'archived' OR (object_key IS NOT NULL AND length(object_key)>0 AND checksum IS NOT NULL AND checksum ~ '^[0-9a-f]{64}$'))
    );
    CREATE INDEX voice_recording_intent ON staging.voice_recordings(intent_id);
    REVOKE DELETE,TRUNCATE ON staging.voice_intents,staging.voice_recordings FROM ut_staging_runtime;
    REVOKE UPDATE,DELETE,TRUNCATE ON staging.voice_events FROM ut_staging_runtime;
    ''')


def downgrade():
    raise RuntimeError('Call reservations, events and recordings must be preserved')
