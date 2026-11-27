"""Run import dispatcher race QA regressions against an explicitly isolated local project only."""
import json,os,shlex,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
compose=['sudo','-n','docker','compose','--project-directory',str(root),*shlex.split(os.environ.get('FOUNDATION_COMPOSE_ARGS',''))]
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
assert os.environ.get('CI')=='true' or config['name'].startswith('ut-qa-'), 'Use an explicitly named ut-qa-* isolated project.'
assert 'db' in config['services'] and config['services']['api']['environment']['DB_HOST']=='db'
assert config['services']['api']['environment']['COMMUNICATIONS_MODE']=='disabled'
source=(root/'tests/import-dispatch-race-integration.py').read_text()
# Keep the real dispatcher running for publication races, but do not launch a
# second Python/Celery/Argon2 import inside its192MiB service cgroup. CI has
# killed that shared-container proof with137. A separate run retains the same
# image, credentials, database, CPU/memory bounds and every business assertion.
subprocess.run([*compose,'run','--rm','--no-deps','-T','dispatcher','python','-'],input=source,text=True,check=True,timeout=180)
