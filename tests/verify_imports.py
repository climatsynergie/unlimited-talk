"""Disposable-only import integration; no managed resources or real contacts."""
import json
import os
from pathlib import Path
import shlex
import subprocess
root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root)]
compose+=shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert config['services']['api']['environment']['DB_HOST']=='db' and 'objectstore' in config['services']
subprocess.run([*compose,'stop','dispatcher'],check=True)
try:
    subprocess.run([*compose,'run','--rm','--no-deps','-T','-e','SPACES_CONFIG_FILE=/run/test-spaces','-v',str(root/'secrets/spaces_config')+':/run/test-spaces:ro','dispatcher','python','-'],input=(root/'tests/imports-integration.py').read_text(),text=True,check=True)
finally:
    subprocess.run([*compose,'start','dispatcher'],check=True)
