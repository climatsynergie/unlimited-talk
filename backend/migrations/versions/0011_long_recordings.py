"""Expand recording metadata bounds without rewriting call or CRM history."""
from alembic import op

revision = '0011_long_recordings'
down_revision = '0010_dialer'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''
    ALTER TABLE staging.voice_recordings
      DROP CONSTRAINT voice_recordings_duration_check,
      ADD CONSTRAINT voice_recordings_duration_check CHECK(duration BETWEEN 0 AND 1800);
    ALTER TABLE staging.voice_archive_jobs
      DROP CONSTRAINT voice_archive_jobs_content_bytes_check,
      ALTER COLUMN content_bytes TYPE bigint,
      ADD CONSTRAINT voice_archive_jobs_content_bytes_check
        CHECK(content_bytes BETWEEN 44 AND 57697536);
    ''')


def downgrade():
    raise RuntimeError('Long recordings and call history must be preserved')
