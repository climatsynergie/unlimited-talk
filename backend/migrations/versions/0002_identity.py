"""Add identities without changing foundation tables or their permissions."""
from alembic import op

revision = '0002_identity'
down_revision = '0001_foundation'
branch_labels = None
depends_on = None


def upgrade():
    # Explicit SQL keeps database constraints visible alongside the domain rules.
    op.execute('''
    CREATE TABLE staging.identity_users (
        id uuid PRIMARY KEY,
        email text NOT NULL UNIQUE CHECK (email=lower(email) AND length(email)<=254),
        display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
        role text NOT NULL CHECK (role IN ('admin','agent')),
        password_hash text NOT NULL,
        is_active boolean NOT NULL DEFAULT true,
        mfa_secret text,
        mfa_pending text,
        mfa_pending_until timestamptz,
        mfa_last_counter bigint NOT NULL DEFAULT -1,
        created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE staging.identity_sessions (
        token_hash text PRIMARY KEY CHECK (length(token_hash)=64),
        csrf_hash text NOT NULL CHECK (length(csrf_hash)=64),
        user_id uuid NOT NULL REFERENCES staging.identity_users(id),
        mfa_verified boolean NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        last_seen_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL
    );
    CREATE INDEX identity_sessions_user ON staging.identity_sessions(user_id);
    CREATE INDEX identity_sessions_expiry ON staging.identity_sessions(expires_at);
    CREATE TABLE staging.identity_invitations (
        id uuid PRIMARY KEY,
        token_hash text NOT NULL UNIQUE CHECK (length(token_hash)=64),
        email text NOT NULL,
        display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
        role text NOT NULL CHECK (role IN ('admin','agent')),
        created_by uuid NOT NULL REFERENCES staging.identity_users(id),
        created_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL,
        used_at timestamptz,
        revoked_at timestamptz
    );
    CREATE UNIQUE INDEX identity_one_pending_invitation ON staging.identity_invitations(email)
        WHERE used_at IS NULL AND revoked_at IS NULL;
    CREATE TABLE staging.identity_password_resets (
        token_hash text PRIMARY KEY CHECK (length(token_hash)=64),
        user_id uuid NOT NULL REFERENCES staging.identity_users(id),
        created_by uuid NOT NULL REFERENCES staging.identity_users(id),
        expires_at timestamptz NOT NULL,
        used_at timestamptz,
        revoked_at timestamptz
    );
    CREATE UNIQUE INDEX identity_one_pending_reset ON staging.identity_password_resets(user_id)
        WHERE used_at IS NULL AND revoked_at IS NULL;
    CREATE TABLE staging.identity_recovery_codes (
        code_hash text PRIMARY KEY CHECK (length(code_hash)=64),
        user_id uuid NOT NULL REFERENCES staging.identity_users(id),
        used_at timestamptz
    );
    CREATE TABLE staging.identity_rate_limits (
        bucket text PRIMARY KEY,
        attempts integer NOT NULL CHECK (attempts>0),
        expires_at timestamptz NOT NULL
    );
    CREATE INDEX identity_rate_limits_expiry ON staging.identity_rate_limits(expires_at);
    CREATE TABLE staging.identity_audit (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        actor_id uuid REFERENCES staging.identity_users(id),
        action text NOT NULL,
        subject_id uuid,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE INDEX identity_audit_created ON staging.identity_audit(created_at DESC);
    REVOKE UPDATE, DELETE, TRUNCATE ON staging.identity_audit FROM ut_staging_runtime;
    REVOKE DELETE ON staging.identity_users FROM ut_staging_runtime;
    ''')


def downgrade():
    raise RuntimeError('Identity data must not be removed by an automatic schema downgrade')
