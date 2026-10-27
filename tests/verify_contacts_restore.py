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

tables=['contacts','contact_history','contact_import_rows','contact_imports','identity_users','campaigns','campaign_stages','campaign_agents','campaign_contacts','contact_notes','campaign_events']
fingerprint='SELECT '+" || ':' || ".join(
    "(SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY row_to_json(t)::text),'')) FROM staging."+table+" t)"
    for table in tables)

before=run('psql','-U','postgres','-d','unlimited_talk_staging','-tAc',fingerprint)
backup=run('pg_dump','-U','postgres','-d','unlimited_talk_staging','--schema=staging','--no-owner','--no-acl','--format=custom')
try:
    run('createdb','-U','postgres','unlimited_talk_restore_test')
    run('pg_restore','-U','postgres','-d','unlimited_talk_restore_test','--exit-on-error','--no-owner','--no-acl',data=backup)
    assert run('psql','-U','postgres','-d','unlimited_talk_restore_test','-tAc',fingerprint)==before
finally:
    run('dropdb','-U','postgres','--if-exists','unlimited_talk_restore_test')
print('Synthetic backup restored into separate disposable database; contacts, history, rows and users preserved: PASS')
