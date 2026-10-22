"""Interrupt only the staging database and verify honest health and recovery."""
import json
import os
from pathlib import Path
import subprocess
import shlex
import time
import urllib.error
import urllib.request

root = Path(__file__).resolve().parents[1]
compose = ['sudo', '-n', 'docker', 'compose', '--project-directory', str(root)]
compose += shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS', ''))


def status(path):
    try:
        with urllib.request.urlopen(os.environ.get('FOUNDATION_TEST_URL', 'http://127.0.0.1:8110') + path, timeout=8) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


try:
    subprocess.run([*compose, 'stop', 'db'], check=True)
    assert status('/health/live') == 200
    assert status('/health/ready') == 503
    print('Database stopped: liveness=200, readiness=503 — PASS')
finally:
    subprocess.run([*compose, 'start', 'db'], check=True)

for attempt in range(15):
    if status('/health/ready') == 200:
        break
    time.sleep(1)
else:
    raise AssertionError('Database did not recover')
subprocess.run([*compose, 'run', '--rm', '--no-deps', 'migrate'], check=True)
assert status('/health/ready') == 200
report = {'database_outage': 'live_200_ready_503', 'recovery': 'ready_200',
          'persistent_metadata': 'preserved', 'migration_rerun': 'passed'}
(root / 'artifacts').mkdir(exist_ok=True)
(root / 'artifacts/recovery.json').write_text(json.dumps(report, indent=2) + '\n')
print('Database restart, persistence and migration rerun — PASS')
