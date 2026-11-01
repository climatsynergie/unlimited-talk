"""Inbound migration must preserve populated CRM, calling and archive history."""
import json,os,shlex,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root)]+shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'
def sql(statement):
    return subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d','unlimited_talk_staging','-v','ON_ERROR_STOP=1','-tAc',statement],text=True).strip()
assert sql('SELECT version_num FROM staging.alembic_version')=='0008_recordings'
tables=['identity_users','identity_audit','contacts','contact_history','campaigns','campaign_contacts','contact_notes','campaign_events','appointments','appointment_events','callbacks','callback_events','voice_intents','voice_events','voice_recordings','voice_archive_jobs']
fingerprint='SELECT '+" || ':' || ".join("(SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY row_to_json(t)::text),'')) FROM staging."+table+' t)' for table in tables)
before=sql(fingerprint)
subprocess.run([*compose,'run','--rm','--no-deps','migrate'],check=True)
assert sql('SELECT version_num FROM staging.alembic_version')=='0009_inbound'
assert sql(fingerprint)==before
assert sql('SELECT count(*) FROM staging.inbound_queues')=='0'
assert sql("SELECT has_table_privilege('ut_staging_runtime','staging.inbound_interactions','UPDATE')::text||':'||has_table_privilege('ut_staging_runtime','staging.inbound_followup_events','DELETE')::text")=='false:false'
print('Inbound migration preserves existing CRM/call/archive history, creates no routing or sample queue, and restricts history writes: PASS')
