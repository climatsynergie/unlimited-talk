"""Durable agent dialer, verified caller inventory and campaign routing."""
from alembic import op

revision = '0010_dialer'
down_revision = '0009_inbound'
branch_labels = depends_on = None


def upgrade():
    op.execute(r'''
    CREATE TABLE staging.voice_numbers (
        id uuid PRIMARY KEY,
        account_sid text NOT NULL CHECK(account_sid ~ '^AC[0-9a-fA-F]{32}$'),
        provider_sid text NOT NULL CHECK(provider_sid ~ '^PN[0-9a-fA-F]{32}$'),
        number text NOT NULL CHECK(number ~ '^\+[1-9][0-9]{8,14}$'),
        name text NOT NULL CHECK(length(name)<=200),
        country text NOT NULL DEFAULT '' CHECK(country='' OR country ~ '^[A-Z]{2}$'),
        voice_enabled boolean NOT NULL,
        is_present boolean NOT NULL DEFAULT true,
        is_active boolean NOT NULL DEFAULT true,
        verified_at timestamptz NOT NULL,
        UNIQUE(account_sid,provider_sid), UNIQUE(account_sid,number),
        UNIQUE(account_sid,id,number)
    );
    CREATE TABLE staging.voice_directory_state (
        account_sid text PRIMARY KEY,
        requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        synchronized_at timestamptz,
        next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        lease_token uuid,
        lease_until timestamptz,
        last_error_code text CHECK(last_error_code IN ('provider_unavailable','provider_response_invalid')),
        CHECK((lease_token IS NULL)=(lease_until IS NULL))
    );
    CREATE TABLE staging.voice_campaign_settings (
        campaign_id uuid PRIMARY KEY REFERENCES staging.campaigns(id),
        enabled boolean NOT NULL DEFAULT false,
        default_number_id uuid REFERENCES staging.voice_numbers(id),
        hours jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(hours)='array'),
        version integer NOT NULL DEFAULT 0 CHECK(version>=0),
        updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        updated_by uuid NOT NULL REFERENCES staging.identity_users(id)
    );
    CREATE TABLE staging.voice_region_rules (
        id uuid PRIMARY KEY,
        campaign_id uuid NOT NULL REFERENCES staging.voice_campaign_settings(campaign_id),
        number_id uuid NOT NULL REFERENCES staging.voice_numbers(id),
        country text NOT NULL DEFAULT '' CHECK(country='' OR country ~ '^[A-Z]{2}$'),
        prefix text NOT NULL DEFAULT '' CHECK(prefix='' OR prefix ~ '^\+[1-9][0-9]{0,13}$'),
        CHECK(country<>'' OR prefix<>''),
        UNIQUE(campaign_id,country,prefix)
    );
    CREATE TABLE staging.voice_dialer_sessions (
        actor_id uuid PRIMARY KEY REFERENCES staging.identity_users(id),
        session_hash text NOT NULL CHECK(length(session_hash)=64),
        browser_id uuid NOT NULL,
        campaign_id uuid NOT NULL REFERENCES staging.campaigns(id),
        generation integer NOT NULL DEFAULT 1 CHECK(generation>0),
        mode text NOT NULL CHECK(mode IN ('running','paused','stopped','booking')),
        lease_until timestamptz NOT NULL,
        hold_token uuid,
        resume_after_hold boolean NOT NULL DEFAULT false,
        updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CHECK((mode='booking')=(hold_token IS NOT NULL))
    );
    ALTER TABLE staging.callbacks ADD CONSTRAINT callbacks_call_context UNIQUE(id,campaign_id,contact_id,owner_id);
    ALTER TABLE staging.voice_intents
        ADD COLUMN campaign_id uuid REFERENCES staging.campaigns(id),
        ADD COLUMN contact_id uuid REFERENCES staging.contacts(id),
        ADD COLUMN callback_id uuid,
        ADD COLUMN callback_version integer CHECK(callback_version>=0),
        ADD COLUMN caller_number_id uuid,
        ADD COLUMN membership_version integer CHECK(membership_version>=0),
        ADD COLUMN attempt_timezone text NOT NULL DEFAULT 'America/Toronto',
        ADD COLUMN dialer_generation integer CHECK(dialer_generation>0),
        ADD COLUMN dialer_browser_id uuid,
        ADD COLUMN settled_at timestamptz,
        ADD COLUMN settled_outcome_rank integer NOT NULL DEFAULT 0 CHECK(settled_outcome_rank BETWEEN 0 AND 3),
        ADD COLUMN settled_membership_version integer CHECK(settled_membership_version>=0),
        ADD FOREIGN KEY(campaign_id,contact_id) REFERENCES staging.campaign_contacts(campaign_id,contact_id),
        ADD FOREIGN KEY(callback_id,campaign_id,contact_id,actor_id) REFERENCES staging.callbacks(id,campaign_id,contact_id,owner_id),
        ADD FOREIGN KEY(account_sid,caller_number_id,caller_number) REFERENCES staging.voice_numbers(account_sid,id,number),
        ADD CHECK(campaign_id IS NULL OR contact_id IS NOT NULL),
        ADD CHECK((callback_id IS NULL)=(callback_version IS NULL)),
        ADD CHECK(callback_id IS NULL OR (campaign_id IS NOT NULL AND contact_id IS NOT NULL)),
        ADD CHECK((dialer_generation IS NULL)=(dialer_browser_id IS NULL)),
        ADD CHECK(dialer_generation IS NULL OR (campaign_id IS NOT NULL AND caller_number_id IS NOT NULL));
    CREATE INDEX voice_attempt_day ON staging.voice_intents(account_sid,destination,consumed_at) WHERE consumed_at IS NOT NULL;
    CREATE INDEX voice_destination_timezone ON staging.voice_intents(account_sid,destination,created_at,id);
    CREATE INDEX voice_campaign_calls ON staging.voice_intents(campaign_id,created_at DESC,id);
    CREATE TABLE staging.voice_completion_jobs (
        intent_id uuid PRIMARY KEY REFERENCES staging.voice_intents(id),
        next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
        completed_at timestamptz,
        last_error boolean NOT NULL DEFAULT false
    );
    CREATE INDEX voice_completion_pending ON staging.voice_completion_jobs(next_attempt_at,intent_id) WHERE completed_at IS NULL;
    -- Historical calls retain their existing CRM meaning. New calls use the
    -- durable completion outbox; migration never invents old dispositions.
    UPDATE staging.voice_intents SET settled_at=clock_timestamp() WHERE state IN ('finished','cancelled','expired');
    REVOKE DELETE,TRUNCATE ON staging.voice_numbers,staging.voice_directory_state,
        staging.voice_campaign_settings,staging.voice_dialer_sessions,staging.voice_completion_jobs FROM ut_staging_runtime;
    ''')


def downgrade():
    raise RuntimeError('Dialer reservations, caller identity and attempt history must be preserved')
