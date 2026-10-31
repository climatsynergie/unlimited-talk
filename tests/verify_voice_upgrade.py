"""Prove the Voice schema preserves populated schema-6 business data."""
import json, os, shlex, subprocess
from pathlib import Path
root = Path(__file__).resolve().parents[1]
compose = ['sudo', '-n', 'docker', 'compose', '--project-directory', str(root)] + shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS', ''))
config = json.loads(subprocess.check_output([*compose, 'config', '--format', 'json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST'] == 'db'


def sql(statement):
    return subprocess.check_output([*compose, 'exec', '-T', 'db', 'psql', '-U', 'postgres', '-d', 'unlimited_talk_staging',
                                   '-v', 'ON_ERROR_STOP=1', '-tAc', statement], text=True).strip()


assert sql('SELECT version_num FROM staging.alembic_version') == '0006_callbacks'
sql("""INSERT INTO staging.callbacks(id,campaign_id,contact_id,owner_id,request_hash,due_at,timezone)
VALUES ('00000000-0000-0000-0000-000000000007','00000000-0000-0000-0000-000000000005',
'00000000-0000-0000-0000-000000000004','00000000-0000-0000-0000-000000000003','migration-fixture',now()+interval '1 day','America/Toronto');
INSERT INTO staging.callback_events(callback_id,actor_id,action,details)
VALUES ('00000000-0000-0000-0000-000000000007','00000000-0000-0000-0000-000000000003','callback.created','{}');""")
tables = ['identity_users','contacts','contact_imports','contact_import_rows','contact_history','campaigns','campaign_stages',
          'campaign_contacts','campaign_agents','contact_notes','campaign_events','appointments','appointment_events','callbacks','callback_events']
fingerprint = 'SELECT ' + " || ':' || ".join("(SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY row_to_json(t)::text),'')) FROM staging." + table + ' t)' for table in tables)
before = sql(fingerprint)
subprocess.run([*compose, 'run', '--rm', '--no-deps', 'migrate','alembic','upgrade','0007_voice'], check=True)
assert sql('SELECT version_num FROM staging.alembic_version') == '0007_voice'
assert sql(fingerprint) == before
print('Voice migration preserves identities, imports, campaigns, calendar and callback history: PASS')
