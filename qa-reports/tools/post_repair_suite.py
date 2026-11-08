"""Exclusive rerun of the changed dispatcher and complete browser regression set."""
import os,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
args=['-p','ut-qa-audit-20261108','-f',str(root/'compose.yaml'),'-f','/tmp/ut-full-qa.yaml','-f',str(root/'qa-reports/tools/coverage-compose.yaml')]
compose=['sudo','-n','docker','compose',*args]
os.environ.update(FOUNDATION_COMPOSE_ARGS=__import__('shlex').join(args),FOUNDATION_TEST_PROJECT='ut-qa-audit-20261108',FOUNDATION_TEST_URL='http://127.0.0.1:18304',GITHUB_SHA='qa-audit-fixed-96f5055',QA_EVIDENCE_MODE='recheck',QA_BROWSER_OBSERVATIONS=str(root/'qa-reports/evidence/browser-observations-recheck.jsonl'))
def check(name,command):
 result=subprocess.run([sys.executable,str(root/'qa-reports/tools/run_check.py'),name,'--',*command],cwd=root)
 if result.returncode:raise SystemExit(result.returncode)
services=['api','worker','dispatcher','voice-reconciler','voice-archiver']
check('post-old-runtime-flush',[*compose,'stop',*services])
(root/'qa-reports/coverage/stop-collector').touch()
p=Path('/tmp/ut-full-qa.yaml');p.write_text(p.read_text().replace('unlimited-talk-qa-audit:fixed','unlimited-talk-qa-audit:dispatch-fixed'))
check('post-environment-start',[*compose,'up','-d','--no-deps','--no-build','--wait','--wait-timeout','180',*services,'gateway'])
for name,script in [('post-dispatch-race','verify_import_dispatch_race.py'),('post-dispatch-imports','verify_imports.py'),('post-dispatch-browser','verify_browser.py')]:
 check(name,[sys.executable,str(root/'tests'/script)])
print('Changed dispatcher, broker integration and entire browser suite: PASS')
