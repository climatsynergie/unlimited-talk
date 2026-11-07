"""Add incoming media routing; install only after the schema-12 compatibility image."""
from alembic import op

revision='0012_incoming_runtime'
down_revision='0011_long_recordings'
branch_labels=depends_on=None


def upgrade():
    op.execute(r'''
    CREATE TABLE staging.inbound_lines (
        queue_id uuid PRIMARY KEY REFERENCES staging.inbound_queues(id),
        account_sid text NOT NULL CHECK(account_sid ~ '^AC[0-9a-fA-F]{32}$'),
        provider_sid text NOT NULL CHECK(provider_sid ~ '^PN[0-9a-fA-F]{32}$'),
        phone text NOT NULL CHECK(phone ~ '^\+[1-9][0-9]{8,14}$'),
        public_origin text NOT NULL,
        route_state text NOT NULL CHECK(route_state IN ('connecting','active','disconnected','disabled')),
        verified_at timestamptz,
        last_checked_at timestamptz,
        last_error text,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        UNIQUE(account_sid,provider_sid),UNIQUE(account_sid,phone)
    );
    CREATE TABLE staging.inbound_registrations (
        id uuid PRIMARY KEY,
        actor_id uuid NOT NULL REFERENCES staging.identity_users(id),
        session_hash text NOT NULL CHECK(session_hash ~ '^[a-f0-9]{64}$'),
        browser_id uuid NOT NULL,
        available boolean NOT NULL DEFAULT false,
        media_ready boolean NOT NULL DEFAULT false,
        ready_since timestamptz NOT NULL DEFAULT clock_timestamp(),
        last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        lease_until timestamptz NOT NULL DEFAULT clock_timestamp(),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        closed_at timestamptz
    );
    CREATE UNIQUE INDEX inbound_registration_actor ON staging.inbound_registrations(actor_id) WHERE closed_at IS NULL;
    CREATE INDEX inbound_registration_presence ON staging.inbound_registrations(ready_since,actor_id)
        WHERE closed_at IS NULL AND available AND media_ready;
    CREATE TABLE staging.inbound_calls (
        id uuid PRIMARY KEY,
        queue_id uuid NOT NULL REFERENCES staging.inbound_queues(id),
        account_sid text NOT NULL CHECK(account_sid ~ '^AC[0-9a-fA-F]{32}$'),
        parent_call_sid text NOT NULL CHECK(parent_call_sid ~ '^CA[0-9a-fA-F]{32}$'),
        caller_number text CHECK(caller_number ~ '^\+[1-9][0-9]{8,14}$'),
        called_number text NOT NULL CHECK(called_number ~ '^\+[1-9][0-9]{8,14}$'),
        caller_fingerprint text NOT NULL CHECK(caller_fingerprint ~ '^[a-f0-9]{64}$'),
        state text NOT NULL DEFAULT 'waiting' CHECK(state IN ('waiting','offered','connected','voicemail','finished')),
        outcome text CHECK(outcome IN ('answered','missed','abandoned','outside_hours','overflowed')),
        agent_id uuid REFERENCES staging.identity_users(id),
        current_offer_id uuid,
        voicemail_emitted_at timestamptz,
        followup_id uuid REFERENCES staging.inbound_followups(id),
        received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        connected_at timestamptz,
        finished_at timestamptz,
        parent_terminal_at timestamptz,
        reconciled_at timestamptz,
        UNIQUE(account_sid,parent_call_sid),
        CHECK((state='finished')=(finished_at IS NOT NULL)),
        CHECK(connected_at IS NULL OR agent_id IS NOT NULL)
    );
    CREATE INDEX inbound_call_recovery ON staging.inbound_calls(reconciled_at NULLS FIRST,received_at,id) WHERE state<>'finished';
    CREATE INDEX inbound_call_queue_history ON staging.inbound_calls(queue_id,received_at DESC,id DESC);
    CREATE INDEX inbound_call_agent_history ON staging.inbound_calls(agent_id,connected_at DESC,id DESC) WHERE agent_id IS NOT NULL;
    CREATE INDEX inbound_followup_due ON staging.inbound_calls(finished_at,id)
        WHERE state='finished' AND outcome<>'answered' AND followup_id IS NULL;
    CREATE TABLE staging.inbound_offers (
        id uuid PRIMARY KEY,
        call_id uuid NOT NULL REFERENCES staging.inbound_calls(id),
        actor_id uuid NOT NULL REFERENCES staging.identity_users(id),
        registration_id uuid NOT NULL REFERENCES staging.inbound_registrations(id),
        session_hash text NOT NULL CHECK(session_hash ~ '^[a-f0-9]{64}$'),
        client_identity text NOT NULL CHECK(client_identity ~ '^ut_in_[a-f0-9]{32}$'),
        child_call_sid text UNIQUE CHECK(child_call_sid ~ '^CA[0-9a-fA-F]{32}$'),
        state text NOT NULL DEFAULT 'offered' CHECK(state IN ('offered','accepted','connected','finished')),
        offered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        accepted_at timestamptz,
        connected_at timestamptz,
        terminal_at timestamptz,
        ended_at timestamptz,
        reject_requested_at timestamptz,
        outcome text CHECK(outcome IN ('completed','busy','no-answer','failed','canceled')),
        duration_seconds integer CHECK(duration_seconds BETWEEN 0 AND 1800),
        last_sequence integer NOT NULL DEFAULT -1 CHECK(last_sequence>=-1),
        UNIQUE(call_id,actor_id),
        CHECK((state='finished')=(ended_at IS NOT NULL))
    );
    CREATE UNIQUE INDEX inbound_one_agent_offer ON staging.inbound_offers(actor_id) WHERE state<>'finished';
    CREATE UNIQUE INDEX inbound_one_call_offer ON staging.inbound_offers(call_id) WHERE state<>'finished';
    CREATE INDEX inbound_offer_actor_history ON staging.inbound_offers(actor_id,offered_at DESC,id DESC);
    CREATE INDEX inbound_offer_connected_history ON staging.inbound_offers(actor_id,offered_at DESC,id DESC)
        WHERE connected_at IS NOT NULL;
    ALTER TABLE staging.inbound_calls ADD CONSTRAINT inbound_current_offer
        FOREIGN KEY(current_offer_id) REFERENCES staging.inbound_offers(id);
    CREATE TABLE staging.inbound_call_events (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        call_id uuid NOT NULL REFERENCES staging.inbound_calls(id),
        kind text NOT NULL,
        fingerprint text NOT NULL CHECK(fingerprint ~ '^[a-f0-9]{64}$'),
        details jsonb NOT NULL CHECK(jsonb_typeof(details)='object'),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        UNIQUE(call_id,kind,fingerprint)
    );
    CREATE INDEX inbound_call_event_history ON staging.inbound_call_events(call_id,id DESC);
    CREATE TABLE staging.inbound_recordings (
        sid text PRIMARY KEY CHECK(sid ~ '^RE[0-9a-fA-F]{32}$'),
        call_id uuid NOT NULL REFERENCES staging.inbound_calls(id),
        offer_id uuid REFERENCES staging.inbound_offers(id),
        call_sid text NOT NULL CHECK(call_sid ~ '^CA[0-9a-fA-F]{32}$'),
        kind text NOT NULL CHECK(kind IN ('conversation','voicemail')),
        duration integer NOT NULL CHECK(duration BETWEEN 0 AND 1800),
        channels integer NOT NULL,
        state text NOT NULL DEFAULT 'pending_archive' CHECK(state IN ('pending_archive','archived')),
        object_key text,
        checksum text CHECK(checksum ~ '^[a-f0-9]{64}$'),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CHECK((kind='conversation' AND channels=2 AND offer_id IS NOT NULL)
          OR (kind='voicemail' AND channels=1 AND offer_id IS NULL AND duration<=120)),
        CHECK(state<>'archived' OR (object_key IS NOT NULL AND checksum IS NOT NULL))
    );
    CREATE INDEX inbound_recordings_call ON staging.inbound_recordings(call_id,created_at,sid);
    CREATE TABLE staging.inbound_archive_jobs (
        recording_sid text PRIMARY KEY REFERENCES staging.inbound_recordings(sid),
        attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
        next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        lease_token uuid,
        lease_until timestamptz,
        last_error_code text,
        content_bytes bigint CHECK(content_bytes BETWEEN 44 AND 57697536),
        sample_rate integer CHECK(sample_rate=8000),
        archived_at timestamptz,
        CHECK((lease_token IS NULL)=(lease_until IS NULL))
    );
    CREATE INDEX inbound_archive_due ON staging.inbound_archive_jobs(next_attempt_at,recording_sid) WHERE archived_at IS NULL;
    REVOKE DELETE,TRUNCATE ON staging.inbound_lines,staging.inbound_registrations,staging.inbound_calls,
        staging.inbound_offers,staging.inbound_recordings,staging.inbound_archive_jobs FROM ut_staging_runtime;
    REVOKE UPDATE,DELETE,TRUNCATE ON staging.inbound_call_events FROM ut_staging_runtime;
    ''')


def downgrade():
    raise RuntimeError('Incoming calls, offers, recordings and follow-up history must be preserved')
