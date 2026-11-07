"""Add incoming runtime tables while preserving populated CRM/call data and grants."""
import json,os,re,shlex,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root),*shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))]
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'
def sql(statement):
 return subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d','unlimited_talk_staging','-v','ON_ERROR_STOP=1','-tAc',statement],text=True).strip()
assert sql('SELECT version_num FROM staging.alembic_version')=='0011_long_recordings'
tables=json.loads(sql("SELECT json_agg(tablename ORDER BY tablename) FROM pg_tables WHERE schemaname='staging' AND tablename<>'alembic_version'"))
assert tables and all(re.fullmatch('[a-z_]+',table) for table in tables)
fingerprint='SELECT '+" || ':' || ".join("(SELECT md5(coalesce(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text),'')) FROM staging."+table+' t)' for table in tables)
before=sql(fingerprint)
old_names=','.join("'"+table+"'" for table in tables)
grants_query="SELECT md5(string_agg(row_to_json(t)::text,'' ORDER BY row_to_json(t)::text)) FROM information_schema.role_table_grants t WHERE table_schema='staging' AND table_name=ANY(ARRAY["+old_names+"])"
grants=sql(grants_query)
subprocess.run([*compose,'run','--rm','--no-deps','migrate','alembic','upgrade','0012_incoming_runtime'],check=True)
assert sql('SELECT version_num FROM staging.alembic_version')=='0012_incoming_runtime'
assert sql(fingerprint)==before
assert sql(grants_query)==grants
new_tables=('inbound_lines','inbound_registrations','inbound_calls','inbound_offers','inbound_call_events','inbound_recordings','inbound_archive_jobs')
for table in new_tables:
 assert sql("SELECT has_table_privilege('ut_staging_runtime','staging."+table+"','SELECT') AND has_table_privilege('ut_staging_runtime','staging."+table+"','INSERT') AND NOT has_table_privilege('ut_staging_runtime','staging."+table+"','DELETE') AND NOT has_table_privilege('ut_staging_runtime','staging."+table+"','TRUNCATE')")=='t'
assert sql("SELECT NOT has_table_privilege('ut_staging_runtime','staging.inbound_call_events','UPDATE')")=='t'
print('Incoming migration: populated CRM/calls and previous grants unchanged; new runtime rights scoped and event journal immutable: PASS')
