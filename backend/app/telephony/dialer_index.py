"""Idempotent, online queue-index maintenance; run explicitly as migrator.

This index changes query performance, not the stored-data schema contract.
Historical migrations remain immutable. No contacts or call states are modified.
"""
from sqlalchemy import text
from app.database import make_engine

NAME = 'staging.campaign_contacts_dialer_queue'


def ensure(engine):
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as db:
        if db.execute(text('SELECT current_user')).scalar_one() != 'ut_staging_migrator':
            raise RuntimeError('Queue index maintenance requires the migration role.')
        version = db.execute(text('SELECT version_num FROM staging.alembic_version')).scalar_one()
        if version not in {'0010_dialer', '0011_long_recordings', '0012_incoming_runtime'}:
            raise RuntimeError('Unsupported queue schema; no index changed.')
        db.execute(text("SET lock_timeout='2s'"))
        db.execute(text("SET statement_timeout='60s'"))
        db.execute(text('''CREATE INDEX CONCURRENTLY IF NOT EXISTS campaign_contacts_dialer_queue
            ON staging.campaign_contacts (campaign_id, queue_position, contact_id) WHERE is_active'''))
        row = db.execute(text('''SELECT i.indisvalid,i.indisready,i.indrelid=to_regclass('staging.campaign_contacts') AS correct_table,pg_get_indexdef(i.indexrelid) AS definition
            FROM pg_index i WHERE i.indexrelid=to_regclass(:name)'''), {'name': NAME}).mappings().one()
        if (not row['indisvalid'] or not row['indisready'] or not row['correct_table']
                or '(campaign_id, queue_position, contact_id)' not in row['definition']
                or 'WHERE is_active' not in row['definition']):
            raise RuntimeError('Existing queue index is invalid or incompatible; no automatic drop.')
        return {'index': NAME, 'valid': True}



def restore_planner(engine, expected_revision):
    """Remove only this incident's overrides after the optimized release is live."""
    import inspect
    import os
    import re
    from app.telephony.dialer_service import candidates, next_call
    if (not re.fullmatch('[a-f0-9]{40}', expected_revision or '')
            or os.environ.get('APP_REVISION') != expected_revision
            or 'candidate_page AS MATERIALIZED' not in inspect.getsource(candidates)
            or 'SET LOCAL jit=off' not in inspect.getsource(next_call)):
        raise RuntimeError('Refusing planner reset before the exact optimized release.')
    with engine.begin() as db:
        if db.execute(text('SELECT current_user')).scalar_one() != 'ut_staging_runtime':
            raise RuntimeError('Planner reset requires the application role.')
        settings = db.execute(text("""SELECT unnest(s.setconfig) FROM pg_db_role_setting s
            JOIN pg_roles r ON r.oid=s.setrole WHERE r.rolname=current_user AND s.setdatabase=0""")).scalars().all()
        actual = dict(item.split('=', 1) for item in settings
                      if item.split('=', 1)[0] in {'jit', 'enable_hashjoin', 'enable_mergejoin'})
        if actual and actual != {'jit': 'off', 'enable_hashjoin': 'off', 'enable_mergejoin': 'off'}:
            raise RuntimeError('Planner settings changed since the incident; review before reset.')
        for setting in ('jit', 'enable_hashjoin', 'enable_mergejoin'):
            # Fixed constants only; restore the recorded previously-unset defaults.
            db.execute(text('ALTER ROLE ut_staging_runtime RESET ' + setting))
        return {'planner_overrides_reset': True, 'revision': expected_revision}


def main():
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('ensure-index', 'restore-planner'), nargs='?', default='ensure-index')
    parser.add_argument('--expected-revision')
    args = parser.parse_args()
    engine = make_engine()
    try:
        result = ensure(engine) if args.action == 'ensure-index' else restore_planner(engine, args.expected_revision)
        print(json.dumps(result))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
