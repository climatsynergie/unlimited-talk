"""Upgrade populated schema 2 to schema 3 in disposable CI PostgreSQL only."""
import json
import os
from pathlib import Path
import shlex
import subprocess
root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root)]
compose+=shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert config['services']['api']['environment']['DB_HOST']=='db' and 'db' in config['services']
subprocess.run([*compose,'up','-d','--wait','db','broker','objectstore'],check=True)
subprocess.run([*compose,'run','--rm','--no-deps','migrate','alembic','upgrade','0002_identity'],check=True)


def sql(statement):
    return subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d','unlimited_talk_staging','-v','ON_ERROR_STOP=1','-tAc',statement],text=True).strip()


assert sql('SELECT version_num FROM staging.alembic_version')=='0002_identity'
sql("INSERT INTO staging.identity_users(id,email,display_name,role,password_hash,is_active) VALUES ('00000000-0000-0000-0000-000000000003','migration-sentinel@example.invalid','Migration sentinel','agent','inactive-sentinel',false)")
statement="SELECT md5(string_agg(row_to_json(u)::text,'' ORDER BY id)) FROM staging.identity_users u"
before=sql(statement)
subprocess.run([*compose,'run','--rm','--no-deps','migrate','alembic','upgrade','0003_contacts'],check=True)
assert sql('SELECT version_num FROM staging.alembic_version')=='0003_contacts'
assert sql(statement)==before
print('Populated identity schema upgraded additively; existing identities preserved: PASS')
