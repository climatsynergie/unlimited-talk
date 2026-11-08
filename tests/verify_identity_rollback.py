"""Switch to the actual preceding app image against the migrated database."""
import json
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root)]
extra=shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
# Once any -f is supplied Compose stops discovering compose.yaml implicitly.
# Keep the base file explicit before adding the temporary rollback override.
if not any(arg in {'-f','--file'} or arg.startswith('--file=') for arg in extra):
    compose+=['-f',str(root/'compose.yaml')]
compose+=extra
base=os.environ.get('FOUNDATION_TEST_URL','http://127.0.0.1:8110')
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'
assert config['services']['api']['environment']['COMMUNICATIONS_MODE']=='disabled'

TABLES=('identity_users','identity_audit','contacts','contact_history','contact_import_rows',
        'campaigns','campaign_contacts','contact_notes','campaign_events','appointments','appointment_events',
        'callbacks','callback_events','voice_intents','voice_events','voice_recordings','voice_archive_jobs',
        'inbound_queues','inbound_queue_agents','inbound_queue_events','inbound_followups','inbound_interactions',
        'inbound_followup_events','voice_numbers','voice_directory_state','voice_campaign_settings',
        'voice_region_rules','voice_dialer_sessions','voice_completion_jobs','inbound_lines','inbound_registrations',
        'inbound_calls','inbound_offers','inbound_call_events','inbound_recordings','inbound_archive_jobs')


def table_snapshot():
    statement='SELECT json_object_agg(name,facts) FROM ('+' UNION ALL '.join(
        "SELECT '"+table+"' AS name,json_build_object('count',count(*),'md5',md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY row_to_json(t)::text),''))) AS facts FROM staging."+table+' t'
        for table in TABLES)+') snapshots'
    return json.loads(subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d',
        'unlimited_talk_staging','-v','ON_ERROR_STOP=1','-tAc',statement],text=True))


def assert_preserved(before,after,phase):
    changes={table:{'before':before['tables'][table],'after':after['tables'][table]}
        for table in TABLES if before['tables'][table]!=after['tables'][table]}
    print(json.dumps({'event':'rollback_fingerprint_comparison','phase':phase,'changed_tables':changes,
        'legacy_equal':before['legacy']==after['legacy']},sort_keys=True),flush=True)
    assert after==before,'Rollback changed identity data or migration revision: '+phase


def snapshot():
    result=subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d',
        'unlimited_talk_staging','-tAc',"SELECT version_num || ':' || (SELECT count(*) FROM staging.identity_users) || ':' || (SELECT count(*) FROM staging.identity_audit) || ':' || (SELECT md5(string_agg(row_to_json(u)::text,'' ORDER BY id)) FROM staging.identity_users u) FROM staging.alembic_version"],text=True).strip()
    revision,users,audit,fingerprint=result.split(':')
    assert revision=='0012_incoming_runtime' and int(users)>0 and int(audit)>0
    extra=subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d','unlimited_talk_staging','-tAc',"SELECT (SELECT md5(coalesce(string_agg(row_to_json(c)::text,'' ORDER BY id),'')) FROM staging.contacts c) || ':' || (SELECT count(*) FROM staging.contact_history) || ':' || (SELECT count(*) FROM staging.contact_import_rows) || ':' || (SELECT count(*) FROM staging.campaigns) || ':' || (SELECT count(*) FROM staging.campaign_contacts) || ':' || (SELECT count(*) FROM staging.contact_notes) || ':' || (SELECT count(*) FROM staging.campaign_events)"],text=True).strip()
    calendar=subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d','unlimited_talk_staging','-tAc',"SELECT (SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM staging.appointments t) || ':' || (SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM staging.appointment_events t)"],text=True).strip()
    callbacks=subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d','unlimited_talk_staging','-tAc',"SELECT (SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM staging.callbacks t) || ':' || (SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM staging.callback_events t)"],text=True).strip()
    voice=subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d','unlimited_talk_staging','-tAc',"SELECT (SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM staging.voice_intents t) || ':' || (SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM staging.voice_events t) || ':' || (SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY sid),'')) FROM staging.voice_recordings t)"],text=True).strip()
    jobs=subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d','unlimited_talk_staging','-tAc',"SELECT md5(coalesce(string_agg(row_to_json(j)::text,'' ORDER BY recording_sid),'')) FROM staging.voice_archive_jobs j"],text=True).strip()
    inbound=subprocess.check_output([*compose,'exec','-T','db','psql','-U','postgres','-d','unlimited_talk_staging','-tAc',"SELECT " + " || ':' || ".join("(SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY row_to_json(t)::text),'')) FROM staging."+table+" t)" for table in ('inbound_queues','inbound_queue_agents','inbound_queue_events','inbound_followups','inbound_interactions','inbound_followup_events','voice_numbers','voice_directory_state','voice_campaign_settings','voice_region_rules','voice_dialer_sessions','voice_completion_jobs','inbound_lines','inbound_registrations','inbound_calls','inbound_offers','inbound_call_events','inbound_recordings','inbound_archive_jobs'))],text=True).strip()
    legacy=result+':'+extra+':'+calendar+':'+callbacks+':'+voice+':'+jobs+':'+inbound
    return {'legacy':legacy,'tables':table_snapshot()}


def ready(revision):
    for _ in range(15):
        try:
            with urllib.request.urlopen(base+'/health/ready',timeout=5) as response:
                row=json.load(response)
            if row['migration']=='0012_incoming_runtime' and row['revision']==revision:
                return
        except (urllib.error.URLError,TimeoutError):
            pass
        time.sleep(1)
    raise AssertionError('Application failed to become ready at expected revision')


before=snapshot()
print(json.dumps({'event':'rollback_fingerprint_before','tables':before['tables'],
    'legacy_sha256':hashlib.sha256(before['legacy'].encode()).hexdigest()},sort_keys=True),flush=True)
old_revision='662b450501a70431b0effbb087501e727111099d'
with tempfile.TemporaryDirectory(prefix='identity-app-rollback-') as tmp:
    override=Path(tmp)/'rollback.yaml'
    override.write_text(json.dumps({'services': {'api': {'image': os.environ.get('IDENTITY_ROLLBACK_IMAGE', 'unlimited-talk-staging-api:identity-rollback')}}}))
    try:
        subprocess.run([*compose,'-f',str(override),'up','-d','--no-deps','--no-build',
                        '--wait','--wait-timeout','120','api'],check=True)
        ready(old_revision)
        assert_preserved(before,snapshot(),'preceding-image')
    finally:
        subprocess.run([*compose,'up','-d','--no-deps','--no-build','--wait',
                        '--wait-timeout','120','api'],check=True)
        ready(os.environ.get('GITHUB_SHA','development'))
assert_preserved(before,snapshot(),'current-image-restored')
print('Actual preceding image serves migrated database; identity data preserved; new application restored: PASS')
