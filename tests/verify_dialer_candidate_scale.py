"""Run scale regression in a new network-isolated, synthetic PostgreSQL only."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from uuid import uuid4

root = Path(__file__).resolve().parents[1]
compose = ['sudo', '-n', 'docker', 'compose', '--project-directory', str(root),
           *shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS', ''))]
config = json.loads(subprocess.check_output([*compose, 'config', '--format', 'json']))
assert config['services']['api']['environment']['DB_HOST'] == 'db'
assert config['services']['api']['environment']['COMMUNICATIONS_MODE'] == 'disabled'
image = os.environ.get('QA_API_IMAGE', 'unlimited-talk-staging-api:foundation')
name = 'ut-candidate-scale-' + uuid4().hex[:12]
docker = ['sudo', '-n', 'docker']
subprocess.run([*docker, 'run', '-d', '--rm', '--name', name, '--network', 'none',
                '--label', 'ut.qa.scope=dialer-candidate-scale', '--memory', '512m', '--cpus', '1',
                '--tmpfs', '/var/lib/postgresql:rw,size=384m',
                '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', config['services']['db']['image'],
                'postgres', '-c', 'cluster_name=ut-candidate-scale-qa'], check=True)
try:
    for _ in range(60):
        probe = subprocess.run([*docker, 'exec', name, 'pg_isready', '-U', 'postgres'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if probe.returncode == 0:
            break
        time.sleep(.5)
    else:
        raise RuntimeError('Isolated scale database did not become ready')
    subprocess.run([*docker, 'run', '--rm', '--network', 'container:' + name,
                    '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m',
                    '--memory', '256m', '--cpus', '1', '--cap-drop', 'ALL',
                    '--security-opt', 'no-new-privileges',
                    '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'PYTHONPATH=/app',
                    '-v', str(root / 'backend/app') + ':/app/app:ro',
                    '-v', str(root / 'tests/candidate-query-scale.py') + ':/tests/candidate-query-scale.py:ro',
                    image, 'python', '/tests/candidate-query-scale.py'], check=True, timeout=180)
finally:
    subprocess.run([*docker, 'stop', '-t', '5', name], check=True)
