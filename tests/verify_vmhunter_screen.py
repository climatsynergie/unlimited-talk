"""Run the complete pre-bridge proof in its own disposable database/network.

The fixed pilot campaign identifier must not collide with the observation proof
or surrounding CRM tests. No managed database or external provider is allowed.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from uuid import uuid4

root=Path(__file__).resolve().parents[1]
proof_script=sys.argv[1] if len(sys.argv)>1 else 'vmhunter-screen-integration.py'
assert proof_script in {'vmhunter-screen-integration.py','vmhunter-integration.py','vmhunter-multicampaign-integration.py','vmhunter-provider-quota-integration.py','vmhunter-cleanup-recovery-integration.py','shift-concurrency-integration.py','shift-pool-integration.py','shift-search-integration.py','reporting-incoming-integration.py'}
base=['sudo','-n','docker','compose','--project-directory',str(root)]
base+=shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
config=json.loads(subprocess.check_output([*base,'config','--format','json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'
image=config['services']['api']['image']
secrets={name:config['secrets'][name] for name in ('postgres_password','migrator_password','runtime_password','identity_key')}
assert all(Path(value['file']).is_absolute() for value in secrets.values())
environment=dict(APP_ENV='staging',COMMUNICATIONS_MODE='disabled',DB_HOST='db',
    DB_NAME='unlimited_talk_staging',DB_USER='ut_staging_runtime',
    DB_PASSWORD_FILE='/run/secrets/runtime_password',IDENTITY_KEY_FILE='/run/secrets/identity_key',
    APP_ORIGIN='http://127.0.0.1:8110',PYTHONPATH='/app')
volumes=[str(root/'tests')+':/tests:ro',str(root/'scripts')+':/scripts:ro']
if os.environ.get('VMHUNTER_USE_LOCAL_SOURCE')=='1':
    assert not os.environ.get('GITHUB_ACTIONS'),'CI must test the actual built source'
    volumes.append(str(root/'backend/app')+':/app/app:ro')
app_service=dict(image=image,user='10001:10001',read_only=True,tmpfs=['/tmp:rw,noexec,nosuid,size=32m'],
    cap_drop=['ALL'],security_opt=['no-new-privileges:true'],mem_limit='256m',
    networks=['isolated'],environment=environment,volumes=volumes,
    secrets=['runtime_password','identity_key'],depends_on={'db':{'condition':'service_healthy'}})
migrate={**app_service,'environment':{**environment,'DB_USER':'ut_staging_migrator',
    'DB_PASSWORD_FILE':'/run/secrets/migrator_password'},'secrets':['migrator_password'],
    'command':['alembic','upgrade','head']}
definition=dict(name='ut-screen-proof-'+uuid4().hex[:12],
    services={
        'db':dict(image=config['services']['db']['image'],networks=['isolated'],
            environment={'POSTGRES_DB':'unlimited_talk_staging','POSTGRES_PASSWORD_FILE':'/run/secrets/postgres_password'},
            secrets=['postgres_password','migrator_password','runtime_password'],
            volumes=[str(root/'scripts/init-db.sh')+':/docker-entrypoint-initdb.d/10-roles.sh:ro'],
            tmpfs=['/var/lib/postgresql:rw,size=256m'],mem_limit='768m',
            healthcheck={'test':['CMD','pg_isready','-U','postgres','-d','unlimited_talk_staging'],
                'interval':'2s','timeout':'2s','retries':30}),
        'migrate':migrate,
        'proof':{**app_service,'command':['python','/tests/'+proof_script]}},
    networks={'isolated':{'internal':True}},secrets=secrets)
if proof_script=='shift-search-integration.py':
    definition['services']['db']['tmpfs']=['/var/lib/postgresql:rw,size=2g']
    definition['services']['db']['mem_limit']='3072m'
    definition['services']['proof']['secrets'].append('migrator_password')
with tempfile.TemporaryDirectory(prefix='ut-screen-compose-') as folder:
    path=Path(folder)/'compose.json';path.write_text(json.dumps(definition))
    command=['sudo','-n','docker','compose','--env-file','/dev/null','--project-directory',str(root),'-f',str(path)]
    try:
        subprocess.run([*command,'run','--rm','migrate'],check=True,timeout=100)
        subprocess.run([*command,'run','--rm','proof'],check=True,timeout=100)
    finally:
        subprocess.run([*command,'down'],check=True,timeout=30)
