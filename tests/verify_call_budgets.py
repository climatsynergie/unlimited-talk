"""Run budget attack regressions only against disposable local PostgreSQL."""
import json,os,shlex,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root),*shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))]
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert config['services']['api']['environment']['DB_HOST']=='db' and 'db' in config['services']
assert config['services']['api']['environment']['COMMUNICATIONS_MODE']=='disabled'
subprocess.run([*compose,'exec','-T','api','python','-'],input=(root/'tests/call-budget-integration.py').read_text(),text=True,check=True,timeout=180)
