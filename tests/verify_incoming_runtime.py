"""Exercise the future additive schema only on the disposable CI database.

This runs after the schema-11 checks. It never downgrades the database and proves
that the preceding compatibility image can serve the new schema before rollout.
"""
import json,os,shlex,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root),*shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))]
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'
assert config['services']['api']['environment']['COMMUNICATIONS_MODE']=='disabled'
future=(root/'backend/migrations/versions/0012_incoming_runtime.py').read_text()
upgrade='''from sqlalchemy import text
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.database import make_engine
engine=make_engine()
with engine.begin() as db:
 assert db.execute(text("SELECT value FROM staging.environment_metadata WHERE key='data_policy'")).scalar_one()=='synthetic_only'
 version=db.execute(text('SELECT version_num FROM staging.alembic_version')).scalar_one()
 assert version in {'0011_long_recordings','0012_incoming_runtime'}
 if version=='0011_long_recordings':
  tables=('identity_users','contacts','campaigns','campaign_contacts','appointments','callbacks','voice_intents','voice_events','voice_recordings','inbound_followups')
  def snapshot():
   return {table:tuple(db.execute(text("SELECT count(*),md5(coalesce(string_agg(md5(row_to_json(t)::text),'' ORDER BY row_to_json(t)::text),'')) FROM staging."+table+" t")).one()) for table in tables}
  before=snapshot()
  namespace={}
  exec(FUTURE,namespace)
  with Operations.context(MigrationContext.configure(db)):namespace['upgrade']()
  assert before==snapshot(),'Existing CRM/call facts changed during additive incoming migration'
  db.execute(text("UPDATE staging.alembic_version SET version_num='0012_incoming_runtime'"))
print('Additive incoming schema installed in disposable database: PASS')
'''.replace('FUTURE',repr(future))
subprocess.run([*compose,'run','--rm','-T','--no-deps','migrate','python','-'],input=upgrade,text=True,check=True,timeout=120)
import urllib.request
with urllib.request.urlopen(os.environ.get('FOUNDATION_TEST_URL','http://127.0.0.1:8110')+'/health/ready',timeout=10) as response:
 assert json.load(response)['migration']=='0012_incoming_runtime'
source=(root/'tests/incoming-integration.py').read_text()
subprocess.run([*compose,'exec','-T','api','python','-'],input=source,text=True,check=True,timeout=180)
