"""Run controlled-call HTTP/PG proof only in a disposable local container."""
import json, os, shlex, subprocess
from pathlib import Path
root = Path(__file__).resolve().parents[1]
compose = ['sudo', '-n', 'docker', 'compose', '--project-directory', str(root)] + shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS', ''))
config = json.loads(subprocess.check_output([*compose, 'config', '--format', 'json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST'] == 'db'
subprocess.run([*compose, 'exec', '-T', 'api', 'python', '-'], input=(root / 'tests/voice-integration.py').read_text(),
               text=True, check=True, timeout=120)
