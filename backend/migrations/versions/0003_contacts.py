"""Add private imports and contacts without changing identity data."""
from alembic import op
revision = '0003_contacts'
down_revision = '0002_identity'
branch_labels = depends_on = None


def upgrade():
    op.execute('''
    CREATE TABLE staging.contacts (
        id uuid PRIMARY KEY,
        phone text NOT NULL UNIQUE CHECK (phone ~ '^\\+[1-9][0-9]{6,14}$'),
        profile jsonb NOT NULL DEFAULT '{}',
        do_not_contact boolean NOT NULL DEFAULT false,
        non_interested boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE staging.contact_imports (
        id uuid PRIMARY KEY,
        created_by uuid NOT NULL REFERENCES staging.identity_users(id),
        filename text NOT NULL CHECK (length(filename) BETWEEN 1 AND 200),
        encoding text NOT NULL CHECK (encoding IN ('utf-8-sig','cp1252')),
        delimiter text CHECK (delimiter IN (',',';',E'\\t')),
        region text NOT NULL DEFAULT 'CA',
        status text NOT NULL DEFAULT 'upload' CHECK (status IN ('upload','mapping','preview','queued','running','completed','discarded')),
        source_key text NOT NULL UNIQUE,
        source_sha256 text,
        source_bytes integer,
        headers jsonb NOT NULL DEFAULT '[]',
        mapping jsonb NOT NULL DEFAULT '{}',
        summary jsonb NOT NULL DEFAULT '{}',
        total integer NOT NULL DEFAULT 0,
        processed integer NOT NULL DEFAULT 0 CHECK (processed>=0 AND processed<=total),
        created integer NOT NULL DEFAULT 0,
        enriched integer NOT NULL DEFAULT 0,
        unchanged integer NOT NULL DEFAULT 0,
        invalid integer NOT NULL DEFAULT 0,
        confirmed_at timestamptz,
        next_publish_at timestamptz NOT NULL DEFAULT now(),
        last_error text,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        completed_at timestamptz
    );
    CREATE INDEX contact_imports_dispatch ON staging.contact_imports(next_publish_at)
        WHERE status IN ('queued','running');
    CREATE TABLE staging.contact_import_rows (
        import_id uuid NOT NULL REFERENCES staging.contact_imports(id),
        row_number integer NOT NULL,
        profile jsonb NOT NULL,
        error text,
        warnings jsonb NOT NULL DEFAULT '[]',
        duplicate_in_file boolean NOT NULL,
        outcome text CHECK (outcome IN ('created','enriched','unchanged','invalid')),
        contact_id uuid REFERENCES staging.contacts(id),
        PRIMARY KEY(import_id,row_number)
    );
    CREATE INDEX contact_import_rows_pending ON staging.contact_import_rows(import_id,row_number) WHERE outcome IS NULL;
    CREATE TABLE staging.contact_history (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        contact_id uuid NOT NULL REFERENCES staging.contacts(id),
        import_id uuid NOT NULL REFERENCES staging.contact_imports(id),
        row_number integer NOT NULL,
        actor_id uuid NOT NULL REFERENCES staging.identity_users(id),
        action text NOT NULL,
        previous_profile jsonb NOT NULL,
        incoming_profile jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE(import_id,row_number)
    );
    CREATE INDEX contact_history_contact ON staging.contact_history(contact_id,id DESC);
    REVOKE UPDATE,DELETE,TRUNCATE ON staging.contact_history FROM ut_staging_runtime;
    REVOKE DELETE,TRUNCATE ON staging.contacts FROM ut_staging_runtime;
    ''')


def downgrade():
    raise RuntimeError('Contact history must not be removed by automatic downgrade')
