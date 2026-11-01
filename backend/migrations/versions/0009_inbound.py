"""Add inbound configuration and manual follow-up without changing call routing."""
from alembic import op
revision = '0009_inbound'
down_revision = '0008_recordings'
branch_labels = depends_on = None


def upgrade():
    op.execute(r'''
    CREATE TABLE staging.inbound_queues (
        id uuid PRIMARY KEY,
        name text NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 120),
        phone text NOT NULL CHECK(phone ~ '^\+[1-9][0-9]{8,14}$'),
        timezone text NOT NULL,
        hours jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(hours)='array' AND jsonb_array_length(hours)<=14),
        max_wait_seconds integer NOT NULL DEFAULT 60 CHECK(max_wait_seconds BETWEEN 10 AND 600),
        offer_seconds integer NOT NULL DEFAULT 20 CHECK(offer_seconds BETWEEN 5 AND 60 AND offer_seconds<=max_wait_seconds),
        is_active boolean NOT NULL DEFAULT true,
        version integer NOT NULL DEFAULT 0 CHECK(version>=0),
        created_by uuid NOT NULL REFERENCES staging.identity_users(id),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE UNIQUE INDEX inbound_queue_name ON staging.inbound_queues(lower(name));
    CREATE UNIQUE INDEX inbound_queue_phone ON staging.inbound_queues(phone);
    CREATE TABLE staging.inbound_queue_agents (
        queue_id uuid NOT NULL REFERENCES staging.inbound_queues(id),
        user_id uuid NOT NULL REFERENCES staging.identity_users(id),
        mode text NOT NULL CHECK(mode IN ('inbound','mixed')),
        is_active boolean NOT NULL DEFAULT true,
        assigned_by uuid NOT NULL REFERENCES staging.identity_users(id),
        assigned_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY(queue_id,user_id)
    );
    CREATE INDEX inbound_agents_user ON staging.inbound_queue_agents(user_id,queue_id) WHERE is_active;
    CREATE TABLE staging.inbound_queue_events (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        queue_id uuid NOT NULL REFERENCES staging.inbound_queues(id),
        actor_id uuid NOT NULL REFERENCES staging.identity_users(id),
        request_id uuid NOT NULL UNIQUE,
        request_hash text NOT NULL CHECK(length(request_hash)=64),
        action text NOT NULL CHECK(action IN ('queue.created','queue.updated')),
        details jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE TABLE staging.inbound_followups (
        id uuid PRIMARY KEY,
        queue_id uuid NOT NULL REFERENCES staging.inbound_queues(id),
        contact_id uuid REFERENCES staging.contacts(id),
        caller_number text CHECK(caller_number ~ '^\+[1-9][0-9]{8,14}$'),
        stage text NOT NULL DEFAULT 'pending' CHECK(stage IN ('pending','claimed','callback','handled')),
        owner_id uuid REFERENCES staging.identity_users(id),
        callback_at timestamptz,
        callback_timezone text,
        version integer NOT NULL DEFAULT 0 CHECK(version>=0),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        closed_at timestamptz,
        UNIQUE(queue_id,id),
        CHECK((stage='pending' AND owner_id IS NULL) OR (stage<>'pending' AND owner_id IS NOT NULL)),
        CHECK((stage='handled')=(closed_at IS NOT NULL)),
        CHECK((stage='callback')=(callback_at IS NOT NULL)),
        CHECK((callback_at IS NULL)=(callback_timezone IS NULL))
    );
    CREATE UNIQUE INDEX inbound_open_number ON staging.inbound_followups(queue_id,caller_number)
        WHERE stage<>'handled' AND caller_number IS NOT NULL;
    CREATE INDEX inbound_followup_board ON staging.inbound_followups(queue_id,stage,created_at DESC,id DESC);
    CREATE TABLE staging.inbound_interactions (
        id uuid PRIMARY KEY,
        queue_id uuid NOT NULL REFERENCES staging.inbound_queues(id),
        followup_id uuid NOT NULL,
        account_sid text NOT NULL CHECK(account_sid ~ '^AC[0-9a-fA-F]{32}$'),
        call_sid text NOT NULL CHECK(call_sid ~ '^CA[0-9a-fA-F]{32}$'),
        caller_number text CHECK(caller_number ~ '^\+[1-9][0-9]{8,14}$'),
        called_number text NOT NULL CHECK(called_number ~ '^\+[1-9][0-9]{8,14}$'),
        outcome text NOT NULL CHECK(outcome IN ('missed','abandoned','outside_hours','overflowed')),
        received_at timestamptz NOT NULL,
        ended_at timestamptz NOT NULL CHECK(ended_at>=received_at),
        fingerprint text NOT NULL CHECK(length(fingerprint)=64),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        UNIQUE(account_sid,call_sid),
        FOREIGN KEY(queue_id,followup_id) REFERENCES staging.inbound_followups(queue_id,id)
    );
    CREATE INDEX inbound_interactions_followup ON staging.inbound_interactions(followup_id,created_at DESC,id DESC);
    CREATE TABLE staging.inbound_followup_events (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        followup_id uuid NOT NULL REFERENCES staging.inbound_followups(id),
        actor_id uuid REFERENCES staging.identity_users(id),
        request_id uuid UNIQUE,
        request_hash text CHECK(length(request_hash)=64),
        action text NOT NULL CHECK(action IN ('call.received','followup.updated','note.added')),
        details jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE INDEX inbound_followup_history ON staging.inbound_followup_events(followup_id,id DESC);
    REVOKE DELETE,TRUNCATE ON staging.inbound_queues,staging.inbound_queue_agents,staging.inbound_followups FROM ut_staging_runtime;
    REVOKE UPDATE,DELETE,TRUNCATE ON staging.inbound_queue_events,staging.inbound_interactions,staging.inbound_followup_events FROM ut_staging_runtime;
    ''')


def downgrade():
    raise RuntimeError('Inbound settings, calls and follow-up history must be preserved')
