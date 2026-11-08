"""Resume after correcting the reusable import fixture, with assertions intact."""
import os,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
os.environ.update(FOUNDATION_COMPOSE_ARGS=f'-p ut-qa-audit-20261108 -f {root}/compose.yaml -f /tmp/ut-full-qa.yaml -f {root}/qa-reports/tools/coverage-compose.yaml',FOUNDATION_TEST_PROJECT='ut-qa-audit-20261108',FOUNDATION_TEST_URL='http://127.0.0.1:18304',GITHUB_SHA='qa-audit-fixed-96f5055',QA_EVIDENCE_MODE='recheck',QA_BROWSER_OBSERVATIONS=str(root/'qa-reports/evidence/browser-observations-recheck.jsonl'))
for name,script in [('post-dispatch-imports','verify_imports.py'),('post-dispatch-browser','verify_browser.py')]:
 result=subprocess.run([sys.executable,str(root/'qa-reports/tools/run_check.py'),name,'--',sys.executable,str(root/'tests'/script)],cwd=root)
 if result.returncode:raise SystemExit(result.returncode)
print('Normal broker imports and complete browser suite on the repaired image: PASS')
