"""Durable recording archive retries and leases, preserving Voice history."""
from alembic import op
revision = '0008_recordings'
down_revision = '0007_voice'
branch_labels = depends_on = None


def upgrade():
    op.execute(r'''
    CREATE TABLE staging.voice_archive_jobs (
        recording_sid text PRIMARY KEY REFERENCES staging.voice_recordings(sid),
        attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 1000000),
        next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        lease_token uuid,
        lease_until timestamptz,
        last_error_code text CHECK(last_error_code ~ '^[a-z_]{1,80}$'),
        archived_at timestamptz,
        content_bytes integer CHECK(content_bytes BETWEEN 44 AND 25165824),
        sample_rate integer CHECK(sample_rate=8000),
        CHECK((lease_token IS NULL)=(lease_until IS NULL)),
        CHECK(archived_at IS NULL OR (content_bytes IS NOT NULL AND sample_rate IS NOT NULL
              AND lease_token IS NULL AND last_error_code IS NULL))
    );
    CREATE INDEX voice_archive_due ON staging.voice_archive_jobs(next_attempt_at,recording_sid)
        WHERE archived_at IS NULL;
    CREATE INDEX voice_recordings_pending ON staging.voice_recordings(created_at,sid)
        WHERE state='pending_archive';
    CREATE INDEX voice_history_time ON staging.voice_intents(created_at DESC,id DESC);
    INSERT INTO staging.voice_archive_jobs(recording_sid)
        SELECT sid FROM staging.voice_recordings WHERE state='pending_archive';
    REVOKE DELETE,TRUNCATE ON staging.voice_archive_jobs FROM ut_staging_runtime;
    ''')


def downgrade():
    raise RuntimeError('Recording jobs and archive history must be preserved')
