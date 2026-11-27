"""Online additive directory indexes. No table rewrite or application-row mutation.

The database owner must first provision pg_trgm in the extensions schema.
Neither application runtime nor migrator is granted extension installation rights.
"""
import argparse,json,os
from sqlalchemy import text
from app.database import make_engine
from app.contacts.search import projection

INDEXES={
    'contacts_directory_order': 'ON staging.contacts (created_at DESC,id)',
    'contacts_directory_search': 'ON staging.contacts USING gin (('+projection()+') extensions.gin_trgm_ops)',
}


def install(engine):
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as db:
        if db.execute(text('SELECT current_user')).scalar_one()!='ut_staging_migrator':
            raise RuntimeError('Query index maintenance requires the migration role.')
        if not db.execute(text("SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='pg_trgm' AND n.nspname='extensions'")).first():
            raise RuntimeError('Database owner must provision pg_trgm in extensions first')
        db.execute(text("SET lock_timeout='2s'"));db.execute(text("SET statement_timeout='120s'"))
        result=[]
        for name,definition in INDEXES.items():
            existing=db.execute(text("SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='staging' AND c.relname=:name"),dict(name=name)).scalar_one_or_none()
            if existing is False:raise RuntimeError('Invalid existing index requires reviewed cleanup')
            db.execute(text('CREATE INDEX CONCURRENTLY IF NOT EXISTS '+name+' '+definition))
            if not db.execute(text("SELECT i.indisvalid AND i.indisready FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='staging' AND c.relname=:name"),dict(name=name)).scalar_one():
                raise RuntimeError('Concurrent index is not ready')
            result.append(dict(name=name,valid=True,created_concurrently=True))
        db.execute(text('ANALYZE staging.contacts'))
        return dict(indexes=result,application_rows_modified=0)


def main():
    p=argparse.ArgumentParser();p.add_argument('--managed',action='store_true');p.add_argument('--local',action='store_true');args=p.parse_args()
    if args.managed == args.local:raise ValueError('Choose exactly one explicit database deployment')
    if os.environ['DB_USER']!='ut_staging_migrator':raise RuntimeError('Migration role required')
    if os.environ.get('DB_DEPLOYMENT','local')!=('managed' if args.managed else 'local'):raise ValueError('Database deployment mismatch')
    engine=make_engine()
    try:
        if args.local:
            with engine.connect() as db:assert db.execute(text("SELECT value FROM staging.environment_metadata WHERE key='data_policy'")).scalar_one()=='synthetic_only'
        print(json.dumps(install(engine)))
    finally:engine.dispose()


if __name__=='__main__':main()
