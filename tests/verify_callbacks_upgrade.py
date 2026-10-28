"""Add callback tables to a populated calendar without rewriting existing data."""
import json,os,shlex,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root)]+shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'
def sql(statement):return subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d','unlimited_talk_staging','-v','ON_ERROR_STOP=1','-tAc',statement],text=True).strip()
assert sql('SELECT version_num FROM staging.alembic_version')=='0005_calendar'
sql("""INSERT INTO staging.appointments(id,campaign_id,contact_id,created_by,request_hash,starts_at,ends_at,timezone,notes)
 VALUES ('00000000-0000-0000-0000-000000000006','00000000-0000-0000-0000-000000000005','00000000-0000-0000-0000-000000000004','00000000-0000-0000-0000-000000000003','migration-fixture','2026-01-01T15:00:00Z','2026-01-01T15:30:00Z','America/Toronto','Preserve original meeting');
 INSERT INTO staging.appointment_events(appointment_id,actor_id,action,details) VALUES
 ('00000000-0000-0000-0000-000000000006','00000000-0000-0000-0000-000000000003','appointment.created','{}');""")
tables=['identity_users','contacts','contact_imports','contact_import_rows','contact_history','campaigns','campaign_stages','campaign_contacts','campaign_agents','contact_notes','campaign_events','appointments','appointment_events']
fingerprint='SELECT '+" || ':' || ".join("(SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY row_to_json(t)::text),'')) FROM staging."+t+' t)' for t in tables)
before=sql(fingerprint)
subprocess.run([*compose,'run','--rm','--no-deps','migrate'],check=True)
assert sql('SELECT version_num FROM staging.alembic_version')=='0006_callbacks'
assert sql(fingerprint)==before
print('Callback migration preserves existing identity, contact, campaign and appointment data: PASS')
