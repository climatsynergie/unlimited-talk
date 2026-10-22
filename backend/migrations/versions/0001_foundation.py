"""Create only environment metadata; no production/customer data."""
from alembic import op
import sqlalchemy as sa

revision = '0001_foundation'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table('environment_metadata',
                           sa.Column('key', sa.Text(), primary_key=True),
                           sa.Column('value', sa.Text(), nullable=False),
                           schema='staging')
    op.bulk_insert(table, [{'key': 'environment', 'value': 'staging'},
                           {'key': 'data_policy', 'value': 'synthetic_only'}])
    # Runtime may read migration metadata but cannot alter the migration marker.
    op.execute('REVOKE INSERT, UPDATE, DELETE ON staging.alembic_version FROM ut_staging_runtime')
    op.execute('REVOKE INSERT, UPDATE, DELETE ON staging.environment_metadata FROM ut_staging_runtime')


def downgrade():
    op.drop_table('environment_metadata', schema='staging')
