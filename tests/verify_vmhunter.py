"""Execute VM Hunter schema/concurrency proof only in disposable local PG."""
import json
import os
from pathlib import Path
import shlex
import subprocess

root = Path(__file__).resolve().parents[1]
compose = ['sudo', '-n', 'docker', 'compose', '--project-directory', str(root)]
compose += shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS', ''))
config = json.loads(subprocess.check_output([*compose, 'config', '--format', 'json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST'] == 'db'
subprocess.run([*compose, 'exec', '-T', 'api', 'python', '-'],
               input=(root / 'tests/vmhunter-integration.py').read_text(),
               text=True, check=True, timeout=90)
