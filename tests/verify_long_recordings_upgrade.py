"""Widen recording bounds without losing existing call facts or role isolation."""
import json, os, shlex, subprocess
from pathlib import Path
root = Path(__file__).resolve().parents[1]
compose = ['sudo', '-n', 'docker', 'compose', '--project-directory', str(root)] + shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS', ''))
config = json.loads(subprocess.check_output([*compose, 'config', '--format', 'json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST'] == 'db'
def sql(statement):
    return subprocess.check_output([*compose, 'exec', '-T', 'db', 'psql', '-U', 'postgres', '-d', 'unlimited_talk_staging', '-v', 'ON_ERROR_STOP=1', '-tAc', statement], text=True).strip()
assert sql('SELECT version_num FROM staging.alembic_version') == '0010_dialer'
sql("""INSERT INTO staging.identity_users(id,email,display_name,role,password_hash,is_active)
 VALUES ('00000000-0000-0000-0000-000000000011','long-recording-migration@example.invalid','Migration archive','agent','inactive-sentinel',false);
 INSERT INTO staging.voice_intents(id,actor_id,session_hash,profile_hash,account_sid,application_sid,caller_number,destination,state,parent_call_sid,expires_at,consumed_at,finished_at)
 VALUES ('00000000-0000-0000-0000-000000000011','00000000-0000-0000-0000-000000000011',repeat('a',64),repeat('b',64),'AC'||repeat('a',32),'AP'||repeat('d',32),'+14165550100','+14165550101','finished','CA'||repeat('1',32),clock_timestamp()+interval '2 minutes',clock_timestamp(),clock_timestamp());
 INSERT INTO staging.voice_recordings(sid,intent_id,call_sid,duration,channels)
 VALUES ('RE'||repeat('1',32),'00000000-0000-0000-0000-000000000011','CA'||repeat('1',32),10,2);
 INSERT INTO staging.voice_archive_jobs(recording_sid) VALUES ('RE'||repeat('1',32));""")
tables = json.loads(sql("SELECT json_agg(tablename ORDER BY tablename) FROM pg_tables WHERE schemaname='staging' AND tablename<>'alembic_version'"))
fingerprint = 'SELECT ' + " || ':' || ".join("(SELECT md5(coalesce(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text),'')) FROM staging." + table + ' t)' for table in tables)
before = sql(fingerprint)
grants = sql("SELECT md5(string_agg(row_to_json(t)::text,'' ORDER BY row_to_json(t)::text)) FROM information_schema.role_table_grants t WHERE table_schema='staging'")
subprocess.run([*compose, 'run', '--rm', '--no-deps', 'migrate', 'alembic', 'upgrade', '0011_long_recordings'], check=True)
assert sql('SELECT version_num FROM staging.alembic_version') == '0011_long_recordings'
assert sql(fingerprint) == before
assert sql("SELECT md5(string_agg(row_to_json(t)::text,'' ORDER BY row_to_json(t)::text)) FROM information_schema.role_table_grants t WHERE table_schema='staging'") == grants
assert sql("SELECT data_type FROM information_schema.columns WHERE table_schema='staging' AND table_name='voice_archive_jobs' AND column_name='content_bytes'") == 'bigint'
# Exercise both enlarged bounds, always rolling back synthetic fixture updates.
assert sql("BEGIN; UPDATE staging.voice_recordings SET duration=1800; UPDATE staging.voice_archive_jobs SET content_bytes=57697536; SELECT true; ROLLBACK;").splitlines()[-2] == 't'
for statement in ('UPDATE staging.voice_recordings SET duration=1801', 'UPDATE staging.voice_archive_jobs SET content_bytes=57697537'):
    outcome = subprocess.run([*compose, 'exec', '-T', 'db', 'psql', '-U', 'postgres', '-d', 'unlimited_talk_staging', '-v', 'ON_ERROR_STOP=1', '-c', 'BEGIN; '+statement+'; ROLLBACK;'], capture_output=True, text=True)
    assert outcome.returncode != 0 and 'check constraint' in outcome.stderr, outcome.stderr
assert sql(fingerprint) == before
print('Recording expansion preserves all populated tables and grants, accepts 30-minute bounds and rejects overflow: PASS')
