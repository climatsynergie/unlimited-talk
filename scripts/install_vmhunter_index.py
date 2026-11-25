"""Add the optional VM event lookup index online; preserves all business rows."""
import argparse,json,os
from sqlalchemy import text
from app.database import make_engine

NAME='voice_vmhunter_lookup'
DDL="""CREATE INDEX CONCURRENTLY IF NOT EXISTS voice_vmhunter_lookup
ON staging.voice_events (kind,intent_id,created_at)
WHERE kind IN ('vmhunter.claim','vmhunter.result','vmhunter.cleanup_verified')"""

def main():
 p=argparse.ArgumentParser();p.add_argument('--managed',action='store_true');p.add_argument('--local',action='store_true');a=p.parse_args()
 assert a.managed != a.local
 assert os.environ['DB_USER']=='ut_staging_migrator'
 assert os.environ.get('DB_DEPLOYMENT','local')==('managed' if a.managed else 'local')
 engine=make_engine()
 with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as db:
  if a.local:assert db.execute(text("SELECT value FROM staging.environment_metadata WHERE key='data_policy'")).scalar_one()=='synthetic_only'
  db.execute(text("SET lock_timeout='2s'"));db.execute(text("SET statement_timeout='60000ms'"))
  existing=db.execute(text("SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='staging' AND c.relname=:name"),{'name':NAME}).scalar_one_or_none()
  assert existing is not False,'Invalid existing index requires reviewed cleanup'
  db.execute(text(DDL))
  valid=db.execute(text("SELECT i.indisvalid AND i.indisready FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='staging' AND c.relname=:name"),{'name':NAME}).scalar_one()
  assert valid
 print(json.dumps(dict(index=NAME,valid=True,created_concurrently=True,rows_modified=0)))
 engine.dispose()

if __name__=='__main__':main()
