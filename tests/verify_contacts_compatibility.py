"""Verify the preceding app can serve an additive contacts schema revision.

Only a disposable local database is supported. This does not apply the actual
contacts migration or claim its business logic is delivered.
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


ready(200,'0002_identity')
try:
    sql("CREATE TABLE staging.contacts_compatibility_probe(id integer PRIMARY KEY); "
        "INSERT INTO staging.contacts_compatibility_probe VALUES (1); "
        "UPDATE staging.alembic_version SET version_num='0003_contacts'")
    ready(200,'0003_contacts')
    sql("UPDATE staging.alembic_version SET version_num='9999_unknown'")
    ready(503)
    sql("UPDATE staging.alembic_version SET version_num='0003_contacts'")
    ready(200,'0003_contacts')
    count=subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d',
        'unlimited_talk_staging','-tAc','SELECT count(*) FROM staging.contacts_compatibility_probe'],text=True)
    assert count.strip()=='1'
finally:
    sql("UPDATE staging.alembic_version SET version_num='0002_identity'; "
        "DROP TABLE IF EXISTS staging.contacts_compatibility_probe")
ready(200,'0002_identity')
print('Contacts compatibility prerequisite: additive revision accepted, unknown rejected, data preserved: PASS')
