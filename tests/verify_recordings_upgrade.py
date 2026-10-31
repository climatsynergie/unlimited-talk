"""Archive schema adds durable jobs without rewriting existing Voice data."""
import json,os,shlex,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root)]+shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'
def sql(statement):
    return subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d','unlimited_talk_staging',
        '-v','ON_ERROR_STOP=1','-tAc',statement],text=True).strip()
assert sql('SELECT version_num FROM staging.alembic_version')=='0007_voice'
sql("""INSERT INTO staging.voice_intents(id,actor_id,session_hash,profile_hash,account_sid,application_sid,
 caller_number,destination,state,parent_call_sid,expires_at,consumed_at,finished_at)
 VALUES ('00000000-0000-0000-0000-000000000008','00000000-0000-0000-0000-000000000003',
 repeat('a',64),repeat('b',64),'AC'||repeat('a',32),'AP'||repeat('d',32),'+14165550100','+14165550101',
 'finished','CA'||repeat('8',32),clock_timestamp()+interval '2 minutes',clock_timestamp(),clock_timestamp());
 INSERT INTO staging.voice_recordings(sid,intent_id,call_sid,duration,channels)
 VALUES ('RE'||repeat('8',32),'00000000-0000-0000-0000-000000000008','CA'||repeat('8',32),10,2);
 INSERT INTO staging.voice_events(intent_id,kind,fingerprint,details)
 VALUES ('00000000-0000-0000-0000-000000000008','recording',repeat('c',64),'{"recording_sid":"migration-fixture"}');""")
tables=['identity_users','contacts','campaigns','appointments','callbacks','voice_intents','voice_events','voice_recordings']
fingerprint='SELECT '+" || ':' || ".join("(SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY row_to_json(t)::text),'')) FROM staging."+table+' t)' for table in tables)
before=sql(fingerprint)
subprocess.run([*compose,'run','--rm','--no-deps','migrate'],check=True)
assert sql('SELECT version_num FROM staging.alembic_version')=='0008_recordings'
assert sql(fingerprint)==before
assert sql("SELECT attempts||':'||(lease_token IS NULL)::text FROM staging.voice_archive_jobs WHERE recording_sid='RE'||repeat('8',32)")=='0:true'
print('Recording archive migration preserves populated Voice and CRM history and backfills pending jobs: PASS')
