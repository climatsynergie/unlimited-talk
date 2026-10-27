"""Prove schema 4 preserves existing contacts/import provenance on upgrade."""
import json
import os
from pathlib import Path
import shlex
import subprocess
root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root)]
compose+=shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'

def sql(statement):
    return subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d','unlimited_talk_staging','-v','ON_ERROR_STOP=1','-tAc',statement],text=True).strip()

assert sql('SELECT version_num FROM staging.alembic_version')=='0003_contacts'
sql("""INSERT INTO staging.contacts(id,phone,profile,do_not_contact,non_interested)
    VALUES ('00000000-0000-0000-0000-000000000004','+14165550101','{"display_name":"Migration sentinel"}',true,true);
    INSERT INTO staging.contact_imports(id,created_by,filename,encoding,status,source_key,total,processed,created,completed_at)
    VALUES ('00000000-0000-0000-0000-000000000004','00000000-0000-0000-0000-000000000003','migration-sentinel.csv','utf-8-sig','completed','synthetic/migration-sentinel.csv',1,1,1,now());
    INSERT INTO staging.contact_import_rows(import_id,row_number,profile,duplicate_in_file,outcome,contact_id)
    VALUES ('00000000-0000-0000-0000-000000000004',2,'{"phone":"+14165550101"}',false,'created','00000000-0000-0000-0000-000000000004');
    INSERT INTO staging.contact_history(contact_id,import_id,row_number,actor_id,action,previous_profile,incoming_profile)
    VALUES ('00000000-0000-0000-0000-000000000004','00000000-0000-0000-0000-000000000004',2,'00000000-0000-0000-0000-000000000003','created','{}','{"display_name":"Migration sentinel"}');""")
tables=['contacts','contact_imports','contact_import_rows','contact_history','identity_users']
fingerprint='SELECT '+" || ':' || ".join("(SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY row_to_json(t)::text),'')) FROM staging."+table+' t)' for table in tables)
before=sql(fingerprint)
subprocess.run([*compose,'run','--rm','--no-deps','migrate'],check=True)
assert sql('SELECT version_num FROM staging.alembic_version')=='0004_campaigns'
assert sql(fingerprint)==before
print('Campaign schema added; identities, contacts, restrictions and import history preserved: PASS')
