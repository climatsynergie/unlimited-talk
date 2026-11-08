"""Run backend QA regressions against an explicitly isolated local project only."""
import json,os,shlex,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root),*shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))]
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert os.environ.get('CI')=='true' or config['name'].startswith('ut-qa-'), 'Use an explicitly named ut-qa-* isolated project.'
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'
assert config['services']['api']['environment']['COMMUNICATIONS_MODE']=='disabled'
source='QUALIFICATION='+repr(json.loads((root/'tests/qualification-fixture.json').read_text()))+'\n'+(root/'tests/backend-reconfirmation-integration.py').read_text()
subprocess.run([*compose,'exec','-T','api','python','-'],input=source,text=True,check=True,timeout=180)
