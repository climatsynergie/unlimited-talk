"""Shared appointments and immutable change history."""
from alembic import op
revision = '0005_calendar'
down_revision = '0004_campaigns'
branch_labels = depends_on = None


def upgrade():
    op.execute('''
    CREATE TABLE staging.appointments (
        id uuid PRIMARY KEY,
        campaign_id uuid NOT NULL REFERENCES staging.campaigns(id),
        contact_id uuid NOT NULL REFERENCES staging.contacts(id),
        created_by uuid NOT NULL REFERENCES staging.identity_users(id),
        request_hash text NOT NULL,
        starts_at timestamptz NOT NULL,
        ends_at timestamptz NOT NULL CHECK (ends_at > starts_at AND ends_at <= starts_at + interval '24 hours'),
        timezone text NOT NULL,
        notes text NOT NULL DEFAULT '' CHECK (length(notes)<=5000),
        status text NOT NULL DEFAULT 'booked' CHECK (status IN ('booked','completed','cancelled','no_show')),
        version integer NOT NULL DEFAULT 0 CHECK (version>=0),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE INDEX appointments_start ON staging.appointments(starts_at,id);
    CREATE INDEX appointments_creator ON staging.appointments(created_by,starts_at,id);
    CREATE INDEX appointments_contact ON staging.appointments(contact_id,starts_at,id);
    CREATE TABLE staging.appointment_events (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        appointment_id uuid NOT NULL REFERENCES staging.appointments(id),
        actor_id uuid NOT NULL REFERENCES staging.identity_users(id),
        action text NOT NULL,
        details jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE INDEX appointment_events_appointment ON staging.appointment_events(appointment_id,id DESC);
    REVOKE DELETE,TRUNCATE ON staging.appointments FROM ut_staging_runtime;
    REVOKE UPDATE,DELETE,TRUNCATE ON staging.appointment_events FROM ut_staging_runtime;
    ''')


def downgrade():
    raise RuntimeError('Appointments and their history must be preserved')
