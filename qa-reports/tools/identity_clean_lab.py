"""Identity last-admin protection requires a fresh database with exactly one admin."""
import os,subprocess,json
from pathlib import Path
root=Path(__file__).resolve().parents[2];project='ut-qa-identity-'+__import__('uuid').uuid4().hex[:12];override=Path('/tmp/ut-qa-identity-final.yaml');override.write_text(Path('/tmp/ut-full-qa.yaml').read_text().replace('18304','18314'))
args=['-p',project,'-f',str(root/'compose.yaml'),'-f',str(override),'-f',str(root/'qa-reports/tools/coverage-compose.yaml')]
compose=['sudo','-n','docker','compose',*args]
os.environ.update(FOUNDATION_COMPOSE_ARGS=__import__('shlex').join(args),FOUNDATION_TEST_PROJECT=project,FOUNDATION_TEST_URL='http://127.0.0.1:18314',GITHUB_SHA='qa-audit-fixed-96f5055')
try:
 subprocess.run([*compose,'up','-d','--no-build','--wait','--wait-timeout','180','api','gateway'],check=True)
 for name in ('foundation','identity'):
  result=subprocess.run(['python3',str(root/'qa-reports/tools/run_check.py'),'clean-'+name,'--','python3',str(root/'tests'/f'verify_{name}.py')],cwd=root)
  if result.returncode:raise SystemExit(result.returncode)
finally:
 subprocess.run([*compose,'stop'],check=False)
