import os,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
os.environ.update(FOUNDATION_COMPOSE_ARGS=f'-p ut-qa-audit-20261108 -f {root}/compose.yaml -f /tmp/ut-full-qa.yaml',FOUNDATION_TEST_URL='http://127.0.0.1:18304',GITHUB_SHA='qa-audit-baseline-96f5055')
checks=['contacts','campaign','calendar','callbacks','voice','recordings','inbound','dialer','long_recordings','incoming']
for name in checks:
 script=root/'tests'/f'verify_{name}_upgrade.py'
 command=[sys.executable,str(root/'qa-reports/tools/run_check.py'),'baseline-migration-'+name,'--',sys.executable,str(script)]
 result=subprocess.run(command,cwd=root)
 if result.returncode:raise SystemExit(result.returncode)
command=['sudo','-n','docker','compose','-p','ut-qa-audit-20261108','-f',str(root/'compose.yaml'),'-f','/tmp/ut-full-qa.yaml','up','-d','--no-build','--wait','--wait-timeout','180']
raise SystemExit(subprocess.run([sys.executable,str(root/'qa-reports/tools/run_check.py'),'baseline-environment-start','--',*command],cwd=root).returncode)
