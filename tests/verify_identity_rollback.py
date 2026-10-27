"""Switch to the actual preceding app image against the migrated database."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root)]
extra=shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
# Once any -f is supplied Compose stops discovering compose.yaml implicitly.
# Keep the base file explicit before adding the temporary rollback override.
if not any(arg in {'-f','--file'} or arg.startswith('--file=') for arg in extra):
    compose+=['-f',str(root/'compose.yaml')]
compose+=extra
base=os.environ.get('FOUNDATION_TEST_URL','http://127.0.0.1:8110')
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'


def snapshot():
    result=subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d',
        'unlimited_talk_staging','-tAc',"SELECT version_num || ':' || (SELECT count(*) FROM staging.identity_users) || ':' || (SELECT count(*) FROM staging.identity_audit) || ':' || (SELECT md5(string_agg(row_to_json(u)::text,'' ORDER BY id)) FROM staging.identity_users u) FROM staging.alembic_version"],text=True).strip()
    revision,users,audit,fingerprint=result.split(':')
    assert revision=='0003_contacts' and int(users)>0 and int(audit)>0
    extra=subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d','unlimited_talk_staging','-tAc',"SELECT (SELECT md5(coalesce(string_agg(row_to_json(c)::text,'' ORDER BY id),'')) FROM staging.contacts c) || ':' || (SELECT count(*) FROM staging.contact_history) || ':' || (SELECT count(*) FROM staging.contact_import_rows)"],text=True).strip()
    return result+':'+extra


def ready(revision):
    for _ in range(15):
        try:
            with urllib.request.urlopen(base+'/health/ready',timeout=5) as response:
                row=json.load(response)
            if row['migration']=='0003_contacts' and row['revision']==revision:
                return
        except (urllib.error.URLError,TimeoutError):
            pass
        time.sleep(1)
    raise AssertionError('Application failed to become ready at expected revision')


before=snapshot()
old_revision='423e16b69b5ffbb2f2d7fd4846e0f50f90eaef3e'
with tempfile.TemporaryDirectory(prefix='identity-app-rollback-') as tmp:
    override=Path(tmp)/'rollback.yaml'
    override.write_text('services:\n  api:\n    image: unlimited-talk-staging-api:identity-rollback\n')
    try:
        subprocess.run([*compose,'-f',str(override),'up','-d','--no-deps','--no-build',
                        '--wait','--wait-timeout','120','api'],check=True)
        ready(old_revision)
        assert snapshot()==before,'Rollback changed identity data or migration revision'
    finally:
        subprocess.run([*compose,'up','-d','--no-deps','--no-build','--wait',
                        '--wait-timeout','120','api'],check=True)
        ready(os.environ.get('GITHUB_SHA','development'))
assert snapshot()==before
print('Actual preceding image serves migrated database; identity data preserved; new application restored: PASS')
