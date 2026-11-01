"""The dialer expands populated history without rewriting existing call facts."""
import json,os,shlex,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root)]+shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'
def sql(statement):
    return subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d','unlimited_talk_staging','-v','ON_ERROR_STOP=1','-tAc',statement],text=True).strip()
assert sql('SELECT version_num FROM staging.alembic_version')=='0009_inbound'
columns=['campaign_id','contact_id','callback_id','callback_version','caller_number_id','membership_version',
         'attempt_timezone','dialer_generation','dialer_browser_id','settled_at','settled_outcome_rank','settled_membership_version']
tables=['identity_users','identity_audit','contacts','contact_history','campaigns','campaign_contacts','contact_notes',
    'campaign_events','appointments','appointment_events','callbacks','callback_events','voice_intents','voice_events',
    'voice_recordings','voice_archive_jobs','inbound_queues','inbound_queue_agents','inbound_queue_events',
    'inbound_followups','inbound_interactions','inbound_followup_events']
parts=[]
for table in tables:
    data='(to_jsonb(t)-ARRAY['+','.join("'"+c+"'" for c in columns)+']::text[])' if table=='voice_intents' else 'to_jsonb(t)'
    parts.append("(SELECT md5(coalesce(string_agg("+data+"::text,'' ORDER BY "+data+"::text),'')) FROM staging."+table+' t)')
fingerprint='SELECT '+" || ':' || ".join(parts)
before=sql(fingerprint)
subprocess.run([*compose,'run','--rm','--no-deps','migrate','alembic','upgrade','0010_dialer'],check=True)
assert sql('SELECT version_num FROM staging.alembic_version')=='0010_dialer'
assert sql(fingerprint)==before
for table in ['voice_numbers','voice_directory_state','voice_campaign_settings','voice_region_rules','voice_dialer_sessions','voice_completion_jobs']:
    assert sql('SELECT count(*) FROM staging.'+table)=='0'
    assert sql("SELECT has_table_privilege('ut_staging_runtime','staging."+table+"','TRUNCATE')::text")=='false'
print('Dialer migration preserves existing CRM/call facts, creates no caller/routing/session and retains protected history: PASS')
