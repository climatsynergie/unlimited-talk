"""Validate the final physical image after removing the unused installer."""
import json,os,shlex,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2];override=Path('/tmp/ut-final-hardened.yaml');override.write_text(json.dumps({'services':{s:{'image':'unlimited-talk-qa-audit:dependency-hardened'} for s in ('api','migrate','worker','dispatcher','voice-reconciler','voice-archiver')}}))
args=['-p','ut-qa-audit-20261108','-f',str(root/'compose.yaml'),'-f','/tmp/ut-full-qa.yaml','-f',str(root/'qa-reports/tools/coverage-compose.yaml'),'-f',str(override)]
compose=['sudo','-n','docker','compose',*args]
os.environ.update(FOUNDATION_COMPOSE_ARGS=shlex.join(args),FOUNDATION_TEST_PROJECT='ut-qa-audit-20261108',FOUNDATION_TEST_URL='http://127.0.0.1:18304',GITHUB_SHA='qa-audit-fixed-96f5055',IDENTITY_ROLLBACK_IMAGE='unlimited-talk-qa-audit:rollback-662',QA_BROWSER_OBSERVATIONS=str(root/'qa-reports/evidence/browser-observations-hardened.jsonl'))
def check(name,command):
 result=subprocess.run([sys.executable,str(root/'qa-reports/tools/run_check.py'),name,'--',*command],cwd=root)
 if result.returncode:raise SystemExit(result.returncode)
check('hardened-environment-start',[*compose,'up','-d','--no-build','--wait','--wait-timeout','180'])
for label,script in [('incoming-runtime','verify_incoming_runtime.py'),('voice','verify_voice.py'),('incoming-browser','verify_incoming_browser.py'),('schema','verify_schema_revision.py'),('rollback','verify_identity_rollback.py')]:
 os.environ['QA_EVIDENCE_MODE']='hardened-'+label
 check('hardened-'+label,[sys.executable,str(root/'tests'/script)])
print('Final physical runtime: signed incoming/concurrency, Voice API, real incoming browser, schema and rollback: PASS')
