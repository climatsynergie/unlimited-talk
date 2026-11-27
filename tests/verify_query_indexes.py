"""Verify additive online indexes and runtime-role denial on a local synthetic DB.

Run before the existing image rollback gate so that gate serves the populated
schema including these indexes. Never point this helper at a managed database.
"""
import json,os,shlex,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root),*shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))]
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert config['services']['api']['environment']['DB_HOST']=='db'
assert config['services']['api']['environment']['COMMUNICATIONS_MODE']=='disabled'
source=(root/'scripts/install_query_indexes.py').read_text()
common='''import os
from app.database import make_engine
from sqlalchemy import text
assert os.environ['DB_HOST']=='db' and os.environ['COMMUNICATIONS_MODE']=='disabled'
engine=make_engine()
with engine.connect() as db:
 assert db.execute(text("SELECT value FROM staging.environment_metadata WHERE key='data_policy'")).scalar_one()=='synthetic_only'
namespace={'__name__':'query_index_maintenance'}
exec(SOURCE,namespace)
'''.replace('SOURCE',repr(source))
denial=common+'''
try:
 try:namespace['install'](engine)
 except RuntimeError as error:assert 'migration role' in str(error)
 else:raise AssertionError('Runtime role was allowed index maintenance')
finally:engine.dispose()
print('Runtime index maintenance denied: PASS')
'''
subprocess.run([*compose,'exec','-T','api','python','-'],input=denial,text=True,check=True,timeout=30)
proof=common+'''
def snapshot():
 with engine.connect() as db:
  return {name:tuple(db.execute(text("SELECT count(*),coalesce(sum(hashtextextended(row_to_json(t)::text,0)),0) FROM staging."+name+" t")).one()) for name in ('contacts','voice_intents','voice_events')}
try:
 before=snapshot()
 first=namespace['install'](engine)
 assert namespace['install'](engine)==first
 assert snapshot()==before,'Index maintenance mutated business rows'
 with engine.connect() as db:
  assert db.execute(text('SELECT version_num FROM staging.alembic_version')).scalar_one()=='0012_incoming_runtime'
 print(first)
 print('Online indexes, repeat installation, unchanged business fingerprints and schema: PASS')
finally:engine.dispose()
'''
subprocess.run([*compose,'run','--rm','--no-deps','-T','migrate','python','-'],input=proof,text=True,check=True,timeout=270)
