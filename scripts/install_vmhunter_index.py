"""Add the optional VM event lookup index online; preserves all business rows."""
import argparse,json,os
from sqlalchemy import text
from app.database import make_engine

NAME='voice_vmhunter_lookup'
DDL="""CREATE INDEX CONCURRENTLY IF NOT EXISTS voice_vmhunter_lookup
ON staging.voice_events (kind,intent_id,created_at)
WHERE kind IN ('vmhunter.claim','vmhunter.result','vmhunter.cleanup_verified')"""
INDEXES={
 NAME:DDL,
 'voice_vmhunter_recent_claims':"""CREATE INDEX CONCURRENTLY IF NOT EXISTS voice_vmhunter_recent_claims
 ON staging.voice_events (created_at DESC,intent_id) WHERE kind='vmhunter.claim'""",
 'voice_vmhunter_stopped':"""CREATE INDEX CONCURRENTLY IF NOT EXISTS voice_vmhunter_stopped
 ON staging.voice_events (intent_id)
 WHERE kind='vmhunter.result' AND details->>'stream_stop_confirmed'='true'""",
}

def install(engine):
 with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as db:
  if db.execute(text('SELECT current_user')).scalar_one()!='ut_staging_migrator':
   raise RuntimeError('VM Hunter index maintenance requires the migration role')
  db.execute(text("SET lock_timeout='2s'"));db.execute(text("SET statement_timeout='60000ms'"))
  result=[]
  for name,ddl in INDEXES.items():
   existing=db.execute(text("SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='staging' AND c.relname=:name"),{'name':name}).scalar_one_or_none()
   if existing is False:raise RuntimeError('Invalid existing index requires reviewed cleanup')
   db.execute(text(ddl))
   valid=db.execute(text("SELECT i.indisvalid AND i.indisready FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='staging' AND c.relname=:name"),{'name':name}).scalar_one()
   if not valid:raise RuntimeError('Concurrent index is not ready')
   result.append({'index':name,'valid':True,'created_concurrently':True})
  db.execute(text('ANALYZE staging.voice_events'))
  db.execute(text('ANALYZE staging.voice_intents'))
  return dict(indexes=result,rows_modified=0)

def main():
 p=argparse.ArgumentParser();p.add_argument('--managed',action='store_true');p.add_argument('--local',action='store_true');a=p.parse_args()
 assert a.managed != a.local
 assert os.environ['DB_USER']=='ut_staging_migrator'
 assert os.environ.get('DB_DEPLOYMENT','local')==('managed' if a.managed else 'local')
 engine=make_engine()
 try:
  if a.local:
   with engine.connect() as db:assert db.execute(text("SELECT value FROM staging.environment_metadata WHERE key='data_policy'")).scalar_one()=='synthetic_only'
  print(json.dumps(install(engine)))
 finally:engine.dispose()

if __name__=='__main__':main()
