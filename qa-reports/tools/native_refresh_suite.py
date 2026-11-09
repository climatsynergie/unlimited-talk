"""Sequential native-image refresh verification on disposable synthetic data only."""
import json,os,shlex,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
image="unlimited-talk-qa-audit:native-refresh"
project="ut-qa-native-20261109"
override=Path("/tmp/ut-native-refresh.yaml")
override.write_text("services:\n"+"".join(f"  {s}:\n    image: {image}\n" for s in ("api","migrate","worker","dispatcher","voice-reconciler","voice-archiver"))+"  gateway:\n    ports: !override [\"127.0.0.1:18314:8080\"]\n")
args=["-p",project,"-f",str(root/"compose.yaml"),"-f",str(override)]
compose=["sudo","-n","docker","compose",*args]
os.environ.update(FOUNDATION_COMPOSE_ARGS=shlex.join(args),FOUNDATION_TEST_PROJECT=project,FOUNDATION_TEST_URL="http://127.0.0.1:18314",GITHUB_SHA="qa-native-20261109",IDENTITY_ROLLBACK_IMAGE="unlimited-talk-qa-audit:rollback-662",QA_BROWSER_OBSERVATIONS=str(root/"qa-reports/evidence/browser-observations-native-refresh.jsonl"))
results=[]
def check(name,command):
 result=subprocess.run([sys.executable,str(root/"qa-reports/tools/run_check.py"),"native-refresh-"+name,"--",*command],cwd=root)
 results.append(dict(check=name,exit_code=result.returncode))
 (root/"qa-reports/evidence/native-refresh-suite-results.json").write_text(json.dumps(results,indent=2)+"\n")
 if result.returncode:raise SystemExit(result.returncode)
check("host-units",[sys.executable,"-m","unittest","discover","-s","tests/host","-p","test_*.py","-v"])
check("backend-units",["sudo","-n","docker","run","--rm","--network","none","--read-only","--tmpfs","/tmp:rw,noexec,nosuid,size=32m","--cap-drop","ALL","--security-opt","no-new-privileges","--memory","256m","-v",str(root/"tests")+":/tests:ro","-v",str(root/"scripts")+":/scripts:ro",image,"python","-m","unittest","discover","-s","/tests","-p","test_*.py","-v"])
check("controller-units",["npm","--prefix","frontend","run","test:phone"])
for name in ["contacts","campaign","calendar","callbacks","voice","recordings","inbound","dialer","long_recordings","incoming"]:
 check("migration-"+name,[sys.executable,str(root/"tests"/f"verify_{name}_upgrade.py")])
check("environment-start",[*compose,"up","-d","--no-build","--wait","--wait-timeout","180"])
for name in ["foundation","identity","imports","import_dispatch_race","campaigns","calendar","callbacks","backend_reconfirmation","voice","inbound","dialer","call_budgets","reporting","reporting_incoming","incoming_runtime","browser","agent_workflow","incoming_browser","schema_revision","identity_rollback","contacts_restore","recovery","webhook_ingress"]:
 os.environ["QA_EVIDENCE_MODE"]="native-refresh-"+name
 check(name,[sys.executable,str(root/"tests"/f"verify_{name}.py")])
os.environ["QA_API_IMAGE"]=image
check("resource-budget",[sys.executable,str(root/"tests/verify_json_resource_budget.py"),"--gateway"])
print("Completed native-image refresh; raw command exits recorded individually.")
