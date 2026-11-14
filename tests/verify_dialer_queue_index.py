"""Verify role restriction and repeated online index creation on disposable PG."""
import json
import os
from pathlib import Path
import shlex
import subprocess

root = Path(__file__).resolve().parents[1]
compose = ['sudo', '-n', 'docker', 'compose', '--project-directory', str(root),
           *shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS', ''))]
config = json.loads(subprocess.check_output([*compose, 'config', '--format', 'json']))
assert config['services']['api']['environment']['DB_HOST'] == 'db'
assert config['services']['api']['environment']['COMMUNICATIONS_MODE'] == 'disabled'
source = '''from app.database import make_engine
from app.telephony.dialer_index import ensure
engine=make_engine()
try:
 try:ensure(engine)
 except RuntimeError as error:assert str(error)=='Queue index maintenance requires the migration role.'
 else:raise AssertionError('Runtime role must not create the index')
finally:engine.dispose()
print('Runtime role denied index maintenance: PASS')
'''
subprocess.run([*compose, 'exec', '-T', 'api', 'python', '-'], input=source, text=True, check=True, timeout=30)
for _ in range(2):
    subprocess.run([*compose, 'run', '--rm', '-T', '--no-deps', 'migrate',
                    'python', '-m', 'app.telephony.dialer_index'], check=True, timeout=90)
print('Online dialer index and idempotency: PASS')
restore = """import os
from app.database import make_engine
from sqlalchemy import text
from app.telephony.dialer_index import restore_planner
engine=make_engine()
try:
 with engine.connect() as db:
  assert db.execute(text("SELECT value FROM staging.environment_metadata WHERE key='data_policy'")).scalar_one()=='synthetic_only'
 try:restore_planner(engine,'0'*40)
 except RuntimeError as error:assert 'exact optimized release' in str(error)
 else:raise AssertionError('Wrong release must not reset role settings')
 # Simulate release identity only in this isolated helper process; no image or
 # running server identity is changed by the negative/positive guard fixtures.
 os.environ['APP_REVISION']='f'*40
 with engine.begin() as db:
  for key in ('jit','enable_hashjoin','enable_mergejoin'):
   db.execute(text('ALTER ROLE ut_staging_runtime SET '+key+'=off'))
 assert restore_planner(engine,'f'*40)['planner_overrides_reset'] is True
 with engine.connect() as db:
  values=db.execute(text("SELECT unnest(s.setconfig) FROM pg_db_role_setting s JOIN pg_roles r ON r.oid=s.setrole WHERE r.rolname=current_user AND s.setdatabase=0")).scalars().all()
  assert not any(v.split('=',1)[0] in {'jit','enable_hashjoin','enable_mergejoin'} for v in values)
 with engine.begin() as db:db.execute(text('ALTER ROLE ut_staging_runtime SET jit=on'))
 try:restore_planner(engine,'f'*40)
 except RuntimeError as error:assert 'changed since the incident' in str(error)
 else:raise AssertionError('Conflicting settings must require review')
finally:
 with engine.begin() as db:
  for key in ('jit','enable_hashjoin','enable_mergejoin'):
   db.execute(text('ALTER ROLE ut_staging_runtime RESET '+key))
 engine.dispose()
print('Planner reset release/conflict guards and restoration: PASS')
"""
subprocess.run([*compose, 'exec', '-T', 'api', 'python', '-'], input=restore, text=True, check=True, timeout=30)
