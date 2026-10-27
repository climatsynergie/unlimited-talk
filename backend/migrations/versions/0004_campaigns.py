"""Add campaign membership and append-only organization history."""
from alembic import op
revision = '0004_campaigns'
down_revision = '0003_contacts'
branch_labels = depends_on = None


def upgrade():
    op.execute('''
    CREATE TABLE staging.campaigns (
        id uuid PRIMARY KEY,
        name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
        description text NOT NULL DEFAULT '' CHECK (length(description)<=2000),
        timezone text NOT NULL,
        is_active boolean NOT NULL DEFAULT true,
        version integer NOT NULL DEFAULT 0,
        created_by uuid NOT NULL REFERENCES staging.identity_users(id),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX campaigns_name ON staging.campaigns(lower(name));
    CREATE TABLE staging.campaign_stages (
        id uuid PRIMARY KEY,
        campaign_id uuid NOT NULL REFERENCES staging.campaigns(id),
        name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
        kind text NOT NULL CHECK (kind IN ('new','no_answer','callback','other','appointment','non_interested','do_not_contact','custom')),
        color text NOT NULL CHECK (color IN ('violet','blue','amber','green','rose','slate')),
        position integer NOT NULL CHECK (position>=0),
        is_active boolean NOT NULL DEFAULT true,
        UNIQUE(campaign_id,id),
        CONSTRAINT campaign_stage_position UNIQUE(campaign_id,position) DEFERRABLE INITIALLY DEFERRED
    );
    CREATE UNIQUE INDEX campaign_stage_name ON staging.campaign_stages(campaign_id,lower(name)) WHERE is_active;
    CREATE UNIQUE INDEX campaign_stage_semantics ON staging.campaign_stages(campaign_id,kind) WHERE kind!='custom';
    CREATE TABLE staging.campaign_agents (
        campaign_id uuid NOT NULL REFERENCES staging.campaigns(id),
        user_id uuid NOT NULL REFERENCES staging.identity_users(id),
        assigned_by uuid NOT NULL REFERENCES staging.identity_users(id),
        is_active boolean NOT NULL DEFAULT true,
        assigned_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY(campaign_id,user_id)
    );
    CREATE INDEX campaign_agents_user ON staging.campaign_agents(user_id,campaign_id) WHERE is_active;
    CREATE TABLE staging.campaign_contacts (
        campaign_id uuid NOT NULL REFERENCES staging.campaigns(id),
        contact_id uuid NOT NULL REFERENCES staging.contacts(id),
        stage_id uuid NOT NULL,
        source_import_id uuid REFERENCES staging.contact_imports(id),
        queue_position bigint GENERATED ALWAYS AS IDENTITY,
        version integer NOT NULL DEFAULT 0,
        is_active boolean NOT NULL DEFAULT true,
        enrolled_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY(campaign_id,contact_id),
        FOREIGN KEY(campaign_id,stage_id) REFERENCES staging.campaign_stages(campaign_id,id)
    );
    CREATE INDEX campaign_contacts_column ON staging.campaign_contacts(campaign_id,stage_id,queue_position) WHERE is_active;
    CREATE INDEX campaign_contacts_contact ON staging.campaign_contacts(contact_id,campaign_id) WHERE is_active;
    CREATE TABLE staging.contact_notes (
        id uuid PRIMARY KEY,
        contact_id uuid NOT NULL REFERENCES staging.contacts(id),
        campaign_id uuid NOT NULL REFERENCES staging.campaigns(id),
        actor_id uuid NOT NULL REFERENCES staging.identity_users(id),
        content text NOT NULL CHECK (length(btrim(content)) BETWEEN 1 AND 5000),
        created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX contact_notes_contact ON staging.contact_notes(contact_id,created_at DESC,id);
    CREATE TABLE staging.campaign_events (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        request_id uuid UNIQUE,
        request_hash text,
        campaign_id uuid NOT NULL REFERENCES staging.campaigns(id),
        contact_id uuid REFERENCES staging.contacts(id),
        actor_id uuid NOT NULL REFERENCES staging.identity_users(id),
        action text NOT NULL,
        details jsonb NOT NULL DEFAULT '{}',
        created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE INDEX campaign_events_contact ON staging.campaign_events(campaign_id,contact_id,id DESC);
    REVOKE UPDATE,DELETE,TRUNCATE ON staging.contact_notes,staging.campaign_events FROM ut_staging_runtime;
    REVOKE DELETE,TRUNCATE ON staging.campaigns,staging.campaign_stages,staging.campaign_agents,staging.campaign_contacts FROM ut_staging_runtime;
    ''')


def downgrade():
    raise RuntimeError('Campaign and contact history cannot be automatically removed')
