"""Gate real incoming browser/API/PostgreSQL behavior in a disposable lab."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
extra = shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS', ''))
if not any(x in {'-f', '--file'} or x.startswith('--file=') for x in extra):
    extra += ['-f', str(root / 'compose.yaml')]
compose = ['sudo', '-n', 'docker', 'compose', '--project-directory', str(root), *extra]
config = json.loads(subprocess.check_output([*compose, 'config', '--format', 'json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST'] == 'db'
assert config['services']['api']['environment']['COMMUNICATIONS_MODE'] == 'disabled'

with tempfile.TemporaryDirectory(prefix='ut-incoming-browser-qa-') as folder:
    override = Path(folder) / 'workflow.yaml'
    token = secrets.token_hex(32)
    override.write_text(json.dumps({'services': {'api': {
        'command': ['python', '/qa/incoming_workflow_server.py'],
        'environment': {'QA_FIXTURE_TOKEN': token, 'PYTHONPATH': '/app'},
        'volumes': [str(root / 'tests' / name) + ':/qa/' + name + ':ro' for name in
                    ('agent_workflow_server.py', 'incoming_workflow_server.py')],
    }}}))
    override.chmod(0o600)
    evidence = root / 'qa-reports/evidence/security'
    evidence.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'FOUNDATION_COMPOSE_ARGS': shlex.join([*extra, '-f', str(override)]),
           'QA_REAL_INCOMING_WORKFLOW': '1', 'QA_FIXTURE_TOKEN': token, 'QA_INCOMING_EVIDENCE_DIR': str(evidence)}
    try:
        subprocess.run(['python3', str(root / 'tests/verify_browser.py'), 'incoming-workflow.spec.ts'],
                       cwd=root, env=env, check=True, timeout=240)
        # A skipped test or mocked business API must not satisfy this gate.
        prefix = 'Réception navigateur QA ' + hashlib.sha256(token.encode()).hexdigest()[:16] + ' %'
        proof = '''from app.database import make_engine
from sqlalchemy import text
with make_engine().begin() as db:
 db.execute(text('SET TRANSACTION READ ONLY'))
 count=db.execute(text("""SELECT count(*) FROM staging.inbound_queues q WHERE q.name LIKE :prefix
  AND (SELECT count(*) FROM staging.inbound_calls c WHERE c.queue_id=q.id AND c.state='finished')=2
  AND (SELECT count(*) FROM staging.inbound_calls c WHERE c.queue_id=q.id AND c.outcome='answered' AND c.agent_id IS NOT NULL)=1
  AND (SELECT count(*) FROM staging.inbound_offers o JOIN staging.inbound_calls c ON c.id=o.call_id WHERE c.queue_id=q.id
    AND o.state='finished' AND o.accepted_at IS NOT NULL AND o.connected_at IS NOT NULL AND o.terminal_at IS NOT NULL)=1
  AND (SELECT count(*) FROM staging.inbound_call_events e JOIN staging.inbound_calls c ON c.id=e.call_id
    WHERE c.queue_id=q.id AND e.kind='agent.connected')=1
  AND (SELECT count(*) FROM staging.inbound_followups f WHERE f.queue_id=q.id AND f.stage='pending')=1
  AND (SELECT count(*) FROM staging.inbound_interactions i JOIN staging.inbound_followups f ON f.id=i.followup_id
    WHERE f.queue_id=q.id)=1"""), {'prefix':PREFIX}).scalar_one()
 assert count==1,'Persisted incoming journey evidence missing; a skipped test cannot pass.'
print('Real incoming browser/API/PostgreSQL registration, offer, answer, navigation, hangup and missed-followup evidence: PASS')
'''.replace('PREFIX', repr(prefix))
        subprocess.run([*compose, 'exec', '-T', 'api', 'python', '-'], input=proof, text=True, check=True, timeout=30)
    finally:
        subprocess.run([*compose, 'up', '-d', '--no-deps', '--no-build', '--wait', '--wait-timeout', '120', 'api'], check=True)
