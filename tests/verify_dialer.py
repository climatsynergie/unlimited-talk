"""Run the dialer proof only against disposable local PostgreSQL."""
import json,os,shlex,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root)]+shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'
source='QUALIFICATION='+repr(json.loads((root/'tests/qualification-fixture.json').read_text()))+'\n'+(root/'tests/dialer-integration.py').read_text()
subprocess.run([*compose,'exec','-T','api','python','-'],input=source,text=True,check=True,timeout=180)
