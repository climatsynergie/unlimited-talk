"""Verify application readiness fails closed on unknown schema revisions.

Only a disposable local database is supported. The real preceding image is exercised separately by verify_identity_rollback.py.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import urllib.error
import urllib.request

root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root)]
compose+=shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
base=os.environ.get('FOUNDATION_TEST_URL','http://127.0.0.1:8110')
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'


def sql(statement):
    subprocess.run([*compose,'exec','-T','db','psql','-U','postgres','-d','unlimited_talk_staging',
                    '-v','ON_ERROR_STOP=1','-c',statement],check=True,capture_output=True,text=True)


def ready(expected,version=None):
    try: response=urllib.request.urlopen(base+'/health/ready',timeout=8)
    except urllib.error.HTTPError as error: response=error
    with response:
        assert response.status==expected,response.status
        row=json.load(response)
        if version: assert row['migration']==version


ready(200,'0006_callbacks')
try:
    sql("UPDATE staging.alembic_version SET version_num='0007_voice'")
    ready(200,'0007_voice')
    sql("UPDATE staging.alembic_version SET version_num='0005_calendar'")
    ready(503)
    sql("UPDATE staging.alembic_version SET version_num='0004_campaigns'")
    ready(503)
    sql("UPDATE staging.alembic_version SET version_num='9999_unknown'")
    ready(503)
finally:
    sql("UPDATE staging.alembic_version SET version_num='0006_callbacks'")
ready(200,'0006_callbacks')
print('Application schema guard: older and unknown revisions rejected, current revision restored: PASS')
