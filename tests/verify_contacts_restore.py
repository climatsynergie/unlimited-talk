"""Restore a synthetic schema snapshot into a second disposable local database."""
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

def run(*args,data=None):
    return subprocess.check_output([*compose,'exec','-T','db',*args],input=data)

tables=['contacts','contact_history','contact_import_rows','contact_imports','identity_users','campaigns','campaign_stages','campaign_agents','campaign_contacts','contact_notes','campaign_events','appointments','appointment_events','callbacks','callback_events','voice_intents','voice_events','voice_recordings','voice_archive_jobs','inbound_queues','inbound_queue_agents','inbound_queue_events','inbound_followups','inbound_interactions','inbound_followup_events','voice_numbers','voice_directory_state','voice_campaign_settings','voice_region_rules','voice_dialer_sessions','voice_completion_jobs','inbound_lines','inbound_registrations','inbound_calls','inbound_offers','inbound_call_events','inbound_recordings','inbound_archive_jobs']
fingerprint='SELECT '+" || ':' || ".join(
    "(SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY row_to_json(t)::text),'')) FROM staging."+table+" t)"
    for table in tables)

before=run('psql','-U','postgres','-d','unlimited_talk_staging','-tAc',fingerprint)
# A schema filter alone omits extension definitions, even if its namespace is
# also selected. Include both so the GIN operator class restores into an empty DB.
backup=run('pg_dump','-U','postgres','-d','unlimited_talk_staging','--schema=staging',
           '--schema=extensions','--extension=pg_trgm','--no-owner','--no-acl','--format=custom')
toc=run('pg_restore','--list',data=backup).decode()
assert ' EXTENSION - pg_trgm ' in toc and ' SCHEMA - extensions ' in toc
try:
    run('createdb','-U','postgres','unlimited_talk_restore_test')
    run('pg_restore','-U','postgres','-d','unlimited_talk_restore_test','--exit-on-error','--no-owner','--no-acl',data=backup)
    assert run('psql','-U','postgres','-d','unlimited_talk_restore_test','-tAc',fingerprint)==before
    assert run('psql','-U','postgres','-d','unlimited_talk_restore_test','-tAc',
               "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='pg_trgm'").strip()==b'extensions'
    assert run('psql','-U','postgres','-d','unlimited_talk_restore_test','-tAc',
               "SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='staging' AND c.relname IN ('contacts_directory_order','contacts_directory_search') AND i.indisvalid AND i.indisready").strip()==b'2'
finally:
    run('dropdb','-U','postgres','--if-exists','unlimited_talk_restore_test')
print('Synthetic backup restored into separate disposable database; all selected CRM/outbound tables plus seven incoming tables verified by row fingerprints: PASS')
