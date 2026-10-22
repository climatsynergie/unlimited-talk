"""Exercise the compatibility release against a disposable PostgreSQL database.

Only the local Compose environment is supported: never run against managed DB.
The future additive identity schema is simulated, not its business behavior.
"""
import json
import os
from pathlib import Path
import subprocess
import shlex
import urllib.error
import urllib.request

root = Path(__file__).resolve().parents[1]
compose = ['sudo', '-n', 'docker', 'compose', '--project-directory', str(root)]
compose += shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS', ''))
base_url = os.environ.get('FOUNDATION_TEST_URL', 'http://127.0.0.1:8110')


def sql(statement):
    subprocess.run([*compose, 'exec', '-T', 'db', 'psql', '-U', 'postgres',
                    '-d', 'unlimited_talk_staging', '-v', 'ON_ERROR_STOP=1',
                    '-c', statement], check=True, capture_output=True, text=True)


def ready(expected_status, expected_version=None):
    try:
        response = urllib.request.urlopen(base_url + '/health/ready', timeout=8)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        assert response.status == expected_status, response.status
        result = json.load(response)
        if expected_version:
            assert result['migration'] == expected_version, result
            assert result['database'] == 'connected', result


config = json.loads(subprocess.check_output([*compose, 'config', '--format', 'json']))
assert 'db' in config['services'], 'Disposable local PostgreSQL required'
assert config['services']['api']['environment']['DB_HOST'] == 'db'
ready(200, '0001_foundation')
try:
    # An additional table with durable content models an additive migration.
    # The current application must continue working without deleting this data.
    sql('CREATE TABLE staging.identity_compatibility_probe (id integer PRIMARY KEY); '
        'INSERT INTO staging.identity_compatibility_probe VALUES (1); '
        "UPDATE staging.alembic_version SET version_num='0002_identity'")
    ready(200, '0002_identity')
    sql("UPDATE staging.alembic_version SET version_num='9999_incompatible'")
    ready(503)
    sql("UPDATE staging.alembic_version SET version_num='0002_identity'; "
        "UPDATE staging.environment_metadata SET value='production' WHERE key='environment'")
    ready(503)
    sql("UPDATE staging.environment_metadata SET value='staging' WHERE key='environment'")
    ready(200, '0002_identity')
    result = subprocess.check_output([*compose, 'exec', '-T', 'db', 'psql', '-U',
                                     'postgres', '-d', 'unlimited_talk_staging',
                                     '-tAc', 'SELECT count(*) FROM staging.identity_compatibility_probe'], text=True)
    assert result.strip() == '1', 'Compatibility checks must preserve new-schema data'
finally:
    sql("UPDATE staging.alembic_version SET version_num='0001_foundation'; "
        "UPDATE staging.environment_metadata SET value='staging' WHERE key='environment'; "
        'DROP TABLE IF EXISTS staging.identity_compatibility_probe')
ready(200, '0001_foundation')
print('Known additive schema accepted; unknown schema and wrong environment rejected; data preserved: PASS')
