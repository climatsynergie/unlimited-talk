"""Sequential live-system audit gates: never race API replacement or outage tests."""
import json,os,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
os.environ.update(FOUNDATION_TEST_PROJECT='ut-qa-audit-20261108',QA_BROWSER_OBSERVATIONS=str(root/'qa-reports/evidence/browser-observations.jsonl'),IDENTITY_ROLLBACK_IMAGE='unlimited-talk-qa-audit:rollback-662',FOUNDATION_COMPOSE_ARGS=f'-p ut-qa-audit-20261108 -f {root}/compose.yaml -f /tmp/ut-full-qa.yaml -f {root}/qa-reports/tools/coverage-compose.yaml',FOUNDATION_TEST_URL='http://127.0.0.1:18304',GITHUB_SHA='qa-audit-fixed-96f5055')
startup=['sudo','-n','docker','compose','-p','ut-qa-audit-20261108','-f',str(root/'compose.yaml'),'-f','/tmp/ut-full-qa.yaml','-f',str(root/'qa-reports/tools/coverage-compose.yaml'),'up','-d','--no-deps','--no-build','--wait','--wait-timeout','180','api','worker','dispatcher','voice-reconciler','voice-archiver','gateway']
result=subprocess.run([sys.executable,str(root/'qa-reports/tools/run_check.py'),'final-environment-start','--',*startup],cwd=root)
if result.returncode:raise SystemExit(result.returncode)
# Reload only the disposable gateway after mounted configuration changes.
subprocess.run(startup[:startup.index('up')]+['exec','-T','gateway','nginx','-s','reload'],check=True)
checks=['foundation','identity','imports','import_dispatch_race','campaigns','calendar','callbacks','backend_reconfirmation','voice','inbound','dialer','call_budgets','reporting','reporting_incoming','incoming_runtime','browser','agent_workflow','incoming_browser','schema_revision','identity_rollback','contacts_restore','recovery','webhook_ingress']
results=[]
for name in checks:
 result=subprocess.run([sys.executable,str(root/'qa-reports/tools/run_check.py'),'final-'+name.replace('_','-'),'--',sys.executable,str(root/'qa-reports/tools/identity_clean_lab.py') if name=='identity' else str(root/'tests'/f'verify_{name}.py')],cwd=root)
 results.append({'check':name,'exit_code':result.returncode})
 (root/'qa-reports/evidence/final-suite-results.json').write_text(json.dumps(results,indent=2)+'\n')
raise SystemExit(any(r['exit_code'] for r in results))
