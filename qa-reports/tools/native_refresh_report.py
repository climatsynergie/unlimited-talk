"""Summarize executed refresh evidence without inferring shell exits from CI."""
import datetime,hashlib,json
from pathlib import Path
import yaml
root=Path(__file__).resolve().parents[2];evidence=root/"qa-reports/evidence"
source=root/".github/workflows/ci.yml"
workflow=yaml.safe_load(source.read_text())
ci=json.loads((evidence/"native-refresh/github/latest-summary.json").read_text())
commands={s["name"]:s["run"] for s in workflow["jobs"]["test"]["steps"] if "name" in s and "run" in s}
rows=[]
for run in ci["runs"]:
 for job in run.get("jobs",[]):
  for step in job.get("steps",[]):
   if step["name"] not in commands:continue
   conclusion=step.get("conclusion")
   status={"success":"PASS","failure":"FAIL","cancelled":"BLOCKED","skipped":"NOT TESTED"}.get(conclusion,"NOT TESTED")
   rows.append(dict(name=step["name"],status=status,ci_status=step["status"],conclusion=conclusion,command=commands[step["name"]],shell_exit_code=None,evidence="native-refresh/github/latest-summary.json",source_sha=run["head_sha"]))
out=evidence/"native-refresh/ci-command-results.json"
out.write_text(json.dumps(dict(observed_at=ci["observed_at"],workflow_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),scope="Actual GitHub step conclusions; commands declared in the unchanged source workflow. Public API does not expose numeric process exits or individual test counts.",results=rows),indent=2)+"\n")
local=[]
for name in ["native-refresh-host-units","native-refresh-controller-units","native-refresh-ingress","native-refresh-npm-audit","native-refresh-compose-validation","native-refresh-production-build","native-refresh-apk-selected-gate"]:
 p=evidence/(name+".json")
 if p.exists():local.append(json.loads(p.read_text()))
lines=["# Native refresh executed validation","",f"Snapshot: {ci['observed_at']}. QA source: `{ci['requested_sha']}`.","","## Local executions","","| Check | Result | Exit | Exact command | Evidence |","|---|---|---:|---|---|"]
for r in local:
 import shlex
 lines.append(f"| {r['check']} | {r['status']} | {r['exit_code']} | `{shlex.join(r['command'])}` | [{r['check']}]({Path(r['log']).relative_to('qa-reports')}) |")
lines += ["","The local build failed for disk capacity. The selected APK scanner intentionally fails while zlib-origin advisory matches remain; its native scope/reachability is reviewed in native-library-review.md. Package scanner execution success is not whole-image clearance.","","## Fresh CI steps","","[QA-only Foundation CI](https://github.com/climatsynergie/unlimited-talk/actions/runs/42685739475). Numeric shell exits and raw individual-test counts are unavailable via the public metadata API; no exit0 is invented. Exact declared commands and conclusions are retained in [ci-command-results.json](evidence/native-refresh/ci-command-results.json).","","| Step | Status | CI conclusion |","|---|---|---|"]
for r in rows:lines.append(f"| {r['name']} | {r['status']} | {r['conclusion'] or 'pending'} |")
lines += ["","Earlier local coverage/test counts remain historical source evidence, not freshly measured native-image coverage. Live provider/media tests remain BLOCKED pending credentials, participants and explicit authorization. No real call is initiated by these scripts.",""]
(root/"qa-reports/native-refresh-validation.md").write_text("\n".join(lines))
print(json.dumps(dict(local_checks=len(local),ci_checks=len(rows),ci_step_counts={s:sum(r['status']==s for r in rows) for s in ['PASS','FAIL','BLOCKED','NOT TESTED']})))

run=next(r for r in ci['runs'] if r['head_sha']==ci['requested_sha'])
functional='PASS' if run['status']=='completed' and run['conclusion']=='success' else ('FAIL' if run.get('conclusion')=='failure' else 'NOT TESTED — full run still pending')
readiness=f'''# Native refresh production readiness — 9 November 2026

**Production: NO-GO.** Fresh functional CI: **{functional}**. Native security clearance: **FAIL / unresolved**. Real-call acceptance: **BLOCKED**. A green functional pipeline does not resolve the security or carrier gates.

QA source: `{ci['requested_sha']}` on `qa/full-audit-20261108`. Snapshot: {ci['observed_at']}. [Fresh Foundation CI]({run['html_url']}). New product pins remain confined to QA; main was read-only verified unchanged at `662b450501a70431b0effbb087501e727111099d`. No main merge, deployment, real call, provider-routing change or production-data write occurred.

## Confirmed repairs and compatibility

This continuation updates compatible immutable digest pins for Python3.12.16, Node22.23.4, Redis8.2.11, PostgreSQL18.6 and official Nginx unprivileged1.30.6 slim. They incorporate Alpine musl/zlib revision fixes; slim removes unused curl/Brotli/XML/optional-module packages. The original Node image was already22.23.4; the host22.23.3 observation was not a production-image finding. Exact index/platform digests, verified layer hashes and package inventories are retained in [candidate evidence](evidence/native-refresh/inventories.json).

The prior application defects/fixes and all original regression evidence remain preserved in [findings.md](findings.md). Application logic, dependency lock and regression tests are unchanged by the new native pins except the ingress test's expected gateway image. Product diff since the CI source is empty; [source provenance](evidence/native-refresh/source-state.json).

[Fresh execution ledger](native-refresh-validation.md) supplies exact local commands, observed numeric exits, hashes and the CI command/conclusion index. The local clean build **failed** for disk capacity; that failed attempt is preserved. A remote clean build is evaluated independently. GitHub public step metadata does not expose numeric shell exits or raw individual-test counts: unavailable values remain unknown.

The database gates cover ten populated additive migrations through schema12, schema-version guards, preceding-application image rollback with data fingerprints, synthetic backup/restore and database outage/reconnect. Each gate's actual current conclusion is in the ledger; pending gates are NOT TESTED, never implied PASS. These checks use disposable PostgreSQL/Redis/S3 mocks, not managed/production data. Application rollback is not a destructive schema downgrade or proof of DigitalOcean PITR.

## Remaining blockers

| Blocker | Evidence/status | Required resolution |
|---|---|---|
| Embedded Expat — confirmed HIGH component findings | **FAIL**: official Python3.12.16 actually executes static Expat2.9.0, preceding four2.10 fixes. No directly exploitable application XML route was established. | Tested rebuilt/vendor-fixed Python, or a rigorous narrowly scoped reachability decision; APK Expat upgrade alone cannot relink it. |
| Psycopg bundled OpenSSL | **BLOCKED**:3.3.6 and latest compatible3.3.8 both embed3.5.7; the vendor HIGH DTLS path is not established through PostgreSQL TCP/TLS. Other bundled wheel-native libraries are not exhaustively audited. | Tested maintained native linkage/vendor rebuild and scoped advisory review; a blind wheel bump is insufficient. |
| Selected APK advisory gate | **FAIL**: all five selected snapshots retain the zlib4738 origin range; legacy comparison controls are excluded from the gate. | Review the digest-scoped contributed-code exclusion, or test supported-branch zlib1.4 derivatives. No blanket signed image VEX was claimed. |
| Carrier, audio, recordings and actual concurrent agents | **BLOCKED**: browser/SDK media and provider interactions are simulated in automation. | Explicitly authorized controlled real-call session; first3 agents, then20 with measured audio/latency, occupancy and provider limits. |
| Live audio transfer | **BLOCKED — NOT IMPLEMENTED**: CRM English handoff and unanswered incoming re-offers are different features. | Confirm release scope; implement/test actual warm/blind transfer if required. Do not present it as available. |
| Complete final-image native audit | **BLOCKED / NOT TESTED**: the fresh CI image was not published/exported on the QA branch; local clean build lacked disk. Base layers and the exact preceding runtime wheels were inspected with explicit scopes. | Acquire the immutable tested artifact or rebuild with adequate isolated capacity; generate a full native SBOM/advisory review before release. |
| Cloud/recovery/access acceptance | **BLOCKED / NOT TESTED**: credential rotation, live line routing/IAM, managed PostgreSQL failover/PITR and full object/host/secret restore were not verified here. | Controlled operational review and authorized recovery exercises. Local synthetic restore is insufficient evidence for these systems. |

The [primary native review](native-library-review.md) retains severity, affected versions, reachability limits and sources. Zero Python OSV name/version matches is not zero native vulnerabilities.

## Test counts and coverage

Fresh local measured results: **8 host tests PASS**, **52 controller tests PASS** on the selected Node image; actual Nginx ingress validation **PASS**, including120 accepted burst callbacks and a600-request abuse burst with353 rate-limited responses. Fresh npm audit:zero advisories, exit0. Fresh OSV audit:64 installed distributions from the exact preceding hardened runtime, zero matches, exit0; the unchanged lock does not convert this into a complete final-image native scan. Selected APK scan:exit1, unresolved ranges. Local clean Docker build:exit1, no-space failure.

Fresh CI runs backend tests, real Chromium, real API/PostgreSQL journeys, migrations, concurrency, webhook security and recovery on the new pins. Actual step conclusions and exact declared commands are in the ledger. Fresh individual counts are not fabricated from public metadata. Historical local results remain208 backend tests; browser65PASS/3intentionalSKIP with those gated journeys separately executed2+1PASS; scoped Python coverage91.55% statements/77.01% branches. Coverage was **not remeasured** for this native refresh; see [coverage-summary.md](coverage-summary.md).

Additional **NOT TESTED** scope: full100,000-row PostgreSQL import mixed with20 active agents, all real devices/networks/screen readers, and exhaustive native-wheel components. No100% correctness claim is made.

## One-hour agent session

**No unconditional pilot GO is issued.** The reviewed QA candidate is not deployed. A session on the existing application cannot validate these undeployed repairs or assume schema12 incoming behavior. The known native residuals also require review before a pilot decision. The [short3-agent checklist and30-minute plan](real-call-acceptance-plan.md) is ready; [automation/human/credentials matrix](real-call-acceptance-matrix.md) identifies prerequisites and stop criteria. Preserve the test slot for an explicitly approved, bounded acceptance session after the correct reviewed version and prerequisites are verified; it is not a production launch.
'''
(root/'qa-reports/native-refresh-readiness.md').write_text(readiness)
