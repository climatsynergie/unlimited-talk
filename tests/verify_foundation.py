"""Verify the live foundation from HTTP through PostgreSQL and isolation.

Run after `docker compose up -d`. No real calls, customer records or provider API.
"""
import json
import os
from pathlib import Path
import subprocess
import shlex
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ['sudo', '-n', 'docker', 'compose', '--project-directory', str(ROOT)]
COMPOSE += shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS', ''))


def run(*args, data=None):
    return subprocess.run([*COMPOSE, *args], input=data, text=True,
                          capture_output=True, check=True).stdout


def get(path):
    with urllib.request.urlopen(os.environ.get('FOUNDATION_TEST_URL', 'http://127.0.0.1:8110') + path, timeout=8) as response:
        assert response.status == 200
        assert response.headers['Cache-Control'] == 'no-store'
        assert response.headers['X-Request-ID']
        return json.load(response)


assert get('/api/system')['business_features'] == 'voice_api'
assert get('/health/live')['status'] == 'alive'
assert get('/health/ready') == {'status': 'ready', 'environment': 'staging',
                              'database': 'connected', 'migration': '0007_voice',
                              'communications': 'disabled',
                              'calling_enabled': False,
                              'revision': os.environ.get('GITHUB_SHA', 'development')}
config = json.loads(run('config', '--format', 'json'))
assert config['name'] == os.environ.get('FOUNDATION_TEST_PROJECT', 'unlimited-talk-staging')
assert config['networks']['staging']['internal'] is True
assert 'ports' not in config['services']['db']
assert 'ports' not in config['services']['api']
assert config['services']['gateway']['ports'][0]['host_ip'] == '127.0.0.1'
assert config['services']['api']['read_only'] is True
assert [s['source'] for s in config['services']['api']['secrets']] == ['runtime_password', 'identity_key','spaces_config']
assert config['services']['api']['environment']['COMMUNICATIONS_MODE'] == 'disabled'
for service in config['services'].values():
    for mount in service.get('volumes', []):
        assert 'unlimited-talk-v1045' not in mount.get('source', '')
code = '''
from app.database import make_engine
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
import os,socket
engine=make_engine()
with engine.connect() as db:
    assert db.execute(text('SELECT current_user')).scalar_one() == 'ut_staging_runtime'
    assert db.execute(text("SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname=current_user")).scalar_one() is False
    assert db.execute(text("SELECT has_schema_privilege(current_user,'staging','CREATE')")).scalar_one() is False
    assert db.execute(text("SELECT value FROM staging.environment_metadata WHERE key='data_policy'")).scalar_one() == 'synthetic_only'
try:
    with engine.begin() as db:
        db.execute(text("UPDATE staging.environment_metadata SET value='wrong' WHERE key='environment'"))
except DBAPIError:
    pass
else:
    raise AssertionError('Runtime can change protected environment metadata')
assert os.getuid() == 10001
try:
    socket.create_connection(('1.1.1.1',443),timeout=2).close()
except OSError:
    pass
else:
    raise AssertionError('Staging has unexpected outbound Internet access')
os.environ['COMMUNICATIONS_MODE']='live'
try:
    make_engine()
except RuntimeError:
    pass
else:
    raise AssertionError('Live communications configuration accepted')
print('Database permissions, non-root runtime, egress and configuration guards: PASS')
'''
print(run('exec', '-T', 'api', 'python', '-', data=code).strip())
print('HTTP → API → PostgreSQL → response, migrations and Compose isolation: PASS')
