"""Durable agent-owned callbacks and append-only history."""
from alembic import op
revision='0006_callbacks'
down_revision='0005_calendar'
branch_labels=depends_on=None


def upgrade():
    op.execute('''
    CREATE TABLE staging.callbacks (
        id uuid PRIMARY KEY,
        campaign_id uuid NOT NULL REFERENCES staging.campaigns(id),
        contact_id uuid NOT NULL REFERENCES staging.contacts(id),
        owner_id uuid NOT NULL REFERENCES staging.identity_users(id),
        request_hash text NOT NULL,
        due_at timestamptz NOT NULL,
        timezone text NOT NULL,
        notes text NOT NULL DEFAULT '' CHECK(length(notes)<=5000),
        status text NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','completed','cancelled')),
        version integer NOT NULL DEFAULT 0 CHECK(version>=0),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE UNIQUE INDEX callbacks_one_pending_contact ON staging.callbacks(contact_id) WHERE status='scheduled';
    CREATE INDEX callbacks_owner_due ON staging.callbacks(owner_id,due_at,id) WHERE status='scheduled';
    CREATE INDEX callbacks_pending_due ON staging.callbacks(due_at,id) WHERE status='scheduled';
    CREATE INDEX callbacks_due ON staging.callbacks(due_at,id);
    CREATE TABLE staging.callback_events (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        callback_id uuid NOT NULL REFERENCES staging.callbacks(id),
        actor_id uuid NOT NULL REFERENCES staging.identity_users(id),
        action text NOT NULL,
        details jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE INDEX callback_events_history ON staging.callback_events(callback_id,id DESC);
    REVOKE DELETE,TRUNCATE ON staging.callbacks FROM ut_staging_runtime;
    REVOKE UPDATE,DELETE,TRUNCATE ON staging.callback_events FROM ut_staging_runtime;
    ''')


def downgrade():
    raise RuntimeError('Callback schedules and history must be preserved')
