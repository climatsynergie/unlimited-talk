"""Verify an additive calendar migration preserves every populated schema-4 table."""
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

assert sql('SELECT version_num FROM staging.alembic_version')=='0004_campaigns'
sql("""INSERT INTO staging.campaigns(id,name,timezone,created_by) VALUES
    ('00000000-0000-0000-0000-000000000005','Calendar migration sentinel','America/Toronto','00000000-0000-0000-0000-000000000003');
    INSERT INTO staging.campaign_stages(id,campaign_id,name,kind,color,position) VALUES
    ('00000000-0000-0000-0000-000000000005','00000000-0000-0000-0000-000000000005','À appeler','new','violet',0);
    INSERT INTO staging.campaign_contacts(campaign_id,contact_id,stage_id) VALUES
    ('00000000-0000-0000-0000-000000000005','00000000-0000-0000-0000-000000000004','00000000-0000-0000-0000-000000000005');
    INSERT INTO staging.contact_notes(id,campaign_id,contact_id,actor_id,content) VALUES
    ('00000000-0000-0000-0000-000000000005','00000000-0000-0000-0000-000000000005','00000000-0000-0000-0000-000000000004','00000000-0000-0000-0000-000000000003','Synthetic preservation note');""")
tables=['contacts','contact_imports','contact_import_rows','contact_history','identity_users','campaigns','campaign_stages','campaign_contacts','contact_notes','campaign_events','campaign_agents']
fingerprint='SELECT '+" || ':' || ".join("(SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY row_to_json(t)::text),'')) FROM staging."+t+' t)' for t in tables)
before=sql(fingerprint)
subprocess.run([*compose,'run','--rm','--no-deps','migrate','alembic','upgrade','0005_calendar'],check=True)
assert sql('SELECT version_num FROM staging.alembic_version')=='0005_calendar'
assert sql(fingerprint)==before
print('Calendar migration preserves populated identities, contacts, campaigns, memberships, notes and history: PASS')
