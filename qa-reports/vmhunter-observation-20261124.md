# VM Hunter observation pilot — QA and readiness, 2026-11-24

Code revision: `97a7df97b0b2a0ff013a8afeffd93a4d2a494e15`.
Branch: `qa/vmhunter-pilot-20261124`. No merge, push, application deployment,
real call, real VM Hunter authentication/analysis or customer-audio transfer.
Production remains outside this change. All DB writes below used isolated,
synthetic local PostgreSQL; production data was not modified.

## Delivered scope

A disabled-by-default, optional observation integration for **CHIN LIST 514_REGION**.
It requires both selected agents and consenting test numbers, plus an explicit
processing approval. Current example has zero agents/numbers and is disabled.
Incoming/manual calls and other campaign agents are excluded. Observation never
hangs up, redirects, changes phone/pipeline states or changes reporting totals.

The sidecar translates the PSTN child's inbound Twilio mu-law track to bounded
8kHz PCM, reads VM Hunter decisions while streaming, stops early and explicitly
stops the Twilio stream. Unknown/auth/quota/timeouts and malformed audio keep the
ordinary call running. Transport is TLS to fixed provider hosts. No raw audio,
transcripts or credentials are stored in application logs/history.

The requested company name is **Maisonverte Québec**. No announcement is played
in this observation build. Automatic screening **before** agent connection with
an announcement remains a separate implementation/acceptance step; do not claim
this build already removes voicemail from agents' calls. The vendor advises
against a prompt during the analysis window; test its impact before screening.

Details, boundary decisions and controlled real-call plan:
`deployment/vmhunter/README.md`.

## Confirmed issues found and fixed during development

1. **Medium — observation circuit lost on restart.** A memory-only circuit could
   admit another analysis after an unconfirmed stream stop. The pre-fix implementation
   was executed against the identical DB assertion and failed (exit 1), then the fixed
   implementation passed (exit 0). PostgreSQL now denies new analyses after an
   unconfirmed stop or stale unfinished claim. Real 20-second expiry is also tested.
   This blocks only observation, never agent calls. Recovery intentionally requires
   operator review after provider stop verification; there is no blind auto-reset.
2. **Medium — excessive sidecar secret mounts in the draft overlay.** Extending
   the API service inherited identity and Spaces credentials. The final service is
   standalone and mounts only PostgreSQL CA/runtime password, voice profile, pilot
   configuration and VM Hunter credential. The merged configuration allowlist was
   executed and verified.

No remaining confirmed critical/high defect in this scoped observation change.
This statement is limited to the inspected code and executed tests; it is not a
claim that the entire application or new integration is production-ready.

## Executed results

| Check | Status | Exit | Evidence / interpretation |
| --- | --- | --- | --- |
| Release image build | PASS | 0 | `vmhunter-release-image-20261124.json` / `.log` — Image built from the committed source; no publication. |
| Built-image backend suite | PASS | 0 | `vmhunter-built-image-backend-20261124.json` / `.log` — 291 tests, including 34 protocol/observer/Streams tests and 11 credential tests. |
| Phone/controller unit suite | PASS | 0 | `vmhunter-phone-regressions-20261124.json` / `.log` — 175 tests. |
| Disposable schema and durable concurrency | PASS | 0 | `vmhunter-durable-postgres-20261124.json` / `.log` — Atomic claim, budget, assignment, unchanged phone/pipeline facts, actual 20-second orphan window, restart circuit. |
| Preceding-release compatibility | PASS | 0 | `vmhunter-durable-rollback-read-20261124.json` / `.log` — Four intents read using c93d2d1 code; new event kinds preserved; read-only transaction. |
| Outgoing HTTP/PG regression | PASS | 0 | `vmhunter-voice-api-regressions-final-20261124.json` / `.log` — Signed callbacks, three simultaneous synthetic agents, recording privacy and recovery; observation config unavailable. |
| Dialer HTTP/PG regression | PASS | 0 | `vmhunter-dialer-api-regressions-20261124.json` / `.log` — Automatic progression, permissions, DNC, appointment/callback logic and failure fallback. |
| Incoming HTTP/PG regression | PASS | 0 | `vmhunter-incoming-api-regressions-20261124.json` / `.log` — Incoming signed offers and synthetic concurrent admission, recovery and private audio. Not real PSTN/audio capacity. |
| Optional overlay isolation | PASS | 0 | `vmhunter-overlay-validation-20261124.json` / `.log` — Non-root, read-only, 128MB, no published port and exact five-secret allowlist. |
| Nginx configuration | PASS | 0 | `vmhunter-nginx-config-20261124.json` / `.log` — Actual nginx -t in the pinned gateway image. |
| Image/source identity | PASS | 0 | `vmhunter-image-identity-20261124.json` / `.log` — Built image label and every app Python source match the committed working tree. |
| Browser initial regression | FAIL | 1 | `vmhunter-browser-regressions-final-20261124.json` / `.log` — 50 PASS, 1 FAIL at browserContext.close due to ENOSPC. Assertions were not weakened. |
| Browser focused rerun | PASS | 0 | `vmhunter-browser-disk-recheck-20261124.json` / `.log` — The one affected test PASSED after disk cleanup, with real Chromium. Browser API/provider interfaces are mocked by these existing specs. |
| Restart regression before fix | FAIL | 1 | `vmhunter-circuit-before-expected-failure-20261124.json` / `.log` — Expected FAIL: actual pre-fix Store admitted another analysis after an unconfirmed stream stop. Entire test transaction rolled back. |
| Restart regression after fix | PASS | 0 | `vmhunter-circuit-after-20261124.json` / `.log` — Identical behavioral assertion PASSED with the fixed Store. Entire test transaction rolled back. |

All evidence basenames above are under `qa-reports/evidence/`. The manifest
`vmhunter-validation-manifest-20261124.json` includes actual command arrays,
revision, timings, exits and verified log hashes. Browser case evidence is in
`browser-vmhunter-20261124-results.json` (initial 50/51) and
`browser-vmhunter-recheck-20261124-results.json` (focused 1/1). Initial failure
screenshots/traces remain under `browser-artifacts/vmhunter-20261124/`.
Do not relabel the initial browser invocation PASS: 51 distinct cases have now
been verified across the initial run and the focused rerun.

## Coverage and limits

No new line/branch coverage percentage was measured. Meaningful checks cover
opaque-key storage, private-file handling, capability expiry/purpose/ownership,
replay, campaign/agent/test-number intersection, current assignment, a single
provider claim under competing PG transactions, budget exhaustion, stream
cleanup/cancellation, unknown verdicts, silence and call-screening normalization,
quota/auth/socket failures and restart circuits. The full built-image suite also
checks the locked dependency inventory and absence of package installers.

The WebSocket/HTTP transports were executed on actual local sockets. The remote
provider and Twilio REST service were simulated; passing those tests does not
prove external account permissions, French-Canadian accuracy or audio quality.

## Earlier unsuccessful checks and resolution

Failures are preserved, not suppressed. `vmhunter-qa-image-build-20261124` used a
CLI flag unsupported by this host's legacy Docker builder; a supported build
command succeeded. Two later image builds and one browser teardown hit local
ENOSPC. Only this task's failed build containers and superseded temporary QA
images were removed; existing application/QA data and evidence were preserved.
The final canonical Dockerfile build succeeded with the full code revision.
One discarded build invocation had an incorrect revision argument; it was not
used or published. Final image identity was independently verified.

An early full-unit probe against an older local image reported 282 PASS / 2 FAIL:
that image still contained pip/ensurepip. No policy assertion was removed. The
fresh image passes all 291 tests, including the installer/inventory checks.
The early probe was terminal output, not a recorded run-check artifact; the
subsequent recorded built-image suite is the final verification evidence.

Initial disposable harness failures involved missing PYTHONPATH, an invalid
local APP_ORIGIN, missing synthetic object storage configuration, and a browser
endpoint attached only to an internal Docker network. These were corrected in
local lab configuration (including the same separate gateway/ingress arrangement
as the app), without weakening application origin/permission guards or tests.
See the earlier `vmhunter-postgres-initial`, `vmhunter-browser-api-start*`,
`vmhunter-voice-api-regressions*`, and `vmhunter-browser-regressions` artifacts.

## BLOCKED / NOT TESTED before activation

- **BLOCKED:** boss's pilot agent selection and consenting test numbers are pending.
- **BLOCKED:** user confirmation on processing geography/consent is pending. The
  user asked about Canada; the cloud DPA states US hosting. No ambiguous response
  has been treated as permission to transfer customer audio.
- **NOT TESTED:** real VM Hunter API-key validity, allowance and billing; no config
  frame with the real key was sent because it can consume an analysis.
- **NOT TESTED:** actual Twilio Standard-key Streams permissions, WSS reachability
  through the public gateway, live track direction, latency, two-way audio,
  recording continuity and billed stream stop. Real-call acceptance requires
  explicit authorization and human volunteers.
- **NOT TESTED:** SIGKILL against a live provider stream. The durable gate prevents
  silent resumption after stale claims, but abrupt termination cannot perform
  in-memory stop cleanup; operators must verify/stop orphan streams.
- **NOT TESTED:** fresh dependency/native vulnerability scan for this change. The
  reviewed lock/base pins are unchanged; aiohttp is now explicitly declared at
  the already-installed locked version. A final security scan is a release gate.
- **NOT TESTED:** production throughput/20 real simultaneous agents, transfers and
  quantitative classification accuracy. Admission simulations are not PSTN load.
- **BLOCKED:** normal deployment does not install this optional overlay. A reviewed
  guarded rollout/rollback plan, current full CI and artifact provenance are required.
- **NOT IMPLEMENTED:** automatic voicemail suppression and the pre-agent greeting.
  This build supplies the preceding observation stage and its regression evidence.

The sidecar reuses the existing runtime DB role and Standard Voice profile.
Restrict provider egress/credential permissions and review service DB privileges
before public exposure. The code's REST client targets only Streams; this is not
an assertion that the underlying Standard API key has Streams-only privileges.
The optional service has no public port and a restricted secret mount set.

## Readiness decision

**NO-GO for real pilot activation or production screening.** The isolated
observation preparation and local regression verification are complete. Agent/
number/processing approval, real telephony acceptance, fresh security scanning
and controlled deployment remain gates. Existing live calling was not changed.

## Exact executed commands

### Release image build

```sh
sudo -n docker build --build-arg GIT_REVISION=97a7df97b0b2a0ff013a8afeffd93a4d2a494e15 -t unlimited-talk-vmhunter-qa:committed .
```

Actual exit: `0`. Evidence: `qa-reports/evidence/vmhunter-release-image-20261124.log` and `qa-reports/evidence/vmhunter-release-image-20261124.json`.

### Built-image backend suite

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro -v /home/codexdev/unlimited-talk-qa-audit/scripts:/scripts:ro unlimited-talk-vmhunter-qa:committed python -m unittest discover -s /tests -p 'test_*.py' -v
```

Actual exit: `0`. Evidence: `qa-reports/evidence/vmhunter-built-image-backend-20261124.log` and `qa-reports/evidence/vmhunter-built-image-backend-20261124.json`.

### Phone/controller unit suite

```sh
npm run --prefix frontend test:phone
```

Actual exit: `0`. Evidence: `qa-reports/evidence/vmhunter-phone-regressions-20261124.log` and `qa-reports/evidence/vmhunter-phone-regressions-20261124.json`.

### Disposable schema and durable concurrency

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-lab-20261124/compose-durable.json run --rm proof
```

Actual exit: `0`. Evidence: `qa-reports/evidence/vmhunter-durable-postgres-20261124.log` and `qa-reports/evidence/vmhunter-durable-postgres-20261124.json`.

### Preceding-release compatibility

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-lab-20261124/compose-durable.json run --rm --workdir /tmp -e PYTHONPATH=/previous -e PREVIOUS_REVISION=c93d2d113962ee3875940c0f9f403b5b4c82c0c3 -v /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/vmhunter-lab-20261124/baseline/backend:/previous:ro proof python /tests/vmhunter-rollback-read.py
```

Actual exit: `0`. Evidence: `qa-reports/evidence/vmhunter-durable-rollback-read-20261124.log` and `qa-reports/evidence/vmhunter-durable-rollback-read-20261124.json`.

### Outgoing HTTP/PG regression

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-lab-20261124/compose-final.json run --rm -e VMHUNTER_PILOT_FILE=/not-present proof python /tests/voice-integration.py
```

Actual exit: `0`. Evidence: `qa-reports/evidence/vmhunter-voice-api-regressions-final-20261124.log` and `qa-reports/evidence/vmhunter-voice-api-regressions-final-20261124.json`.

### Dialer HTTP/PG regression

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-lab-20261124/compose-final.json run --rm -e VMHUNTER_PILOT_FILE=/not-present proof python -c 'import json; QUALIFICATION=json.load(open("/tests/qualification-fixture.json")); exec(compile(open("/tests/dialer-integration.py").read(),"/tests/dialer-integration.py","exec"))'
```

Actual exit: `0`. Evidence: `qa-reports/evidence/vmhunter-dialer-api-regressions-20261124.log` and `qa-reports/evidence/vmhunter-dialer-api-regressions-20261124.json`.

### Incoming HTTP/PG regression

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-lab-20261124/compose-final.json run --rm proof python /tests/incoming-integration.py
```

Actual exit: `0`. Evidence: `qa-reports/evidence/vmhunter-incoming-api-regressions-20261124.log` and `qa-reports/evidence/vmhunter-incoming-api-regressions-20261124.json`.

### Optional overlay isolation

```sh
python3 qa-reports/evidence/vmhunter-overlay-check-20261124.py
```

Actual exit: `0`. Evidence: `qa-reports/evidence/vmhunter-overlay-validation-20261124.log` and `qa-reports/evidence/vmhunter-overlay-validation-20261124.json`.

### Nginx configuration

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m --cap-drop ALL --security-opt no-new-privileges -v /home/codexdev/unlimited-talk-qa-audit/scripts/nginx.conf:/etc/nginx/conf.d/default.conf:ro nginx/nginx-unprivileged:stable-alpine-slim@sha256:e333a5b95605942b5e495645ee54fab02b112081de6dbe45d2ead3ef38e03e31 nginx -t
```

Actual exit: `0`. Evidence: `qa-reports/evidence/vmhunter-nginx-config-20261124.log` and `qa-reports/evidence/vmhunter-nginx-config-20261124.json`.

### Image/source identity

```sh
python3 qa-reports/evidence/vmhunter-image-identity-check-20261124.py
```

Actual exit: `0`. Evidence: `qa-reports/evidence/vmhunter-image-identity-20261124.log` and `qa-reports/evidence/vmhunter-image-identity-20261124.json`.

### Browser initial regression

Browser environment: `FOUNDATION_COMPOSE_ARGS=-f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/vmhunter-lab-20261124/compose-final.json`, `FOUNDATION_TEST_URL=http://127.0.0.1:18135`. `QA_EVIDENCE_MODE=vmhunter-20261124`; initial image revision was `development`.

```sh
python3 tests/verify_browser.py autodialer.spec.ts incoming-session.spec.ts phone.spec.ts
```

Actual exit: `1`. Evidence: `qa-reports/evidence/vmhunter-browser-regressions-final-20261124.log` and `qa-reports/evidence/vmhunter-browser-regressions-final-20261124.json`.

### Browser focused rerun

Browser environment: `FOUNDATION_COMPOSE_ARGS=-f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/vmhunter-lab-20261124/compose-final.json`, `FOUNDATION_TEST_URL=http://127.0.0.1:18135`. `GITHUB_SHA=ee42079c9143a0eaf8e09512bda034a782f239f5`, `QA_EVIDENCE_MODE=vmhunter-recheck-20261124`.

```sh
python3 tests/verify_browser.py autodialer.spec.ts -g 'conflit de réservation conserve'
```

Actual exit: `0`. Evidence: `qa-reports/evidence/vmhunter-browser-disk-recheck-20261124.log` and `qa-reports/evidence/vmhunter-browser-disk-recheck-20261124.json`.

### Restart regression before fix

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-lab-20261124/compose-durable.json run --rm -e VMHUNTER_BEFORE_SOURCE_FILE=/tmp/observer-before.py -v /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/vmhunter-observer-before-20261124.py:/tmp/observer-before.py:ro -v /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/vmhunter-circuit-check-20261124.py:/tmp/circuit-check.py:ro proof python /tmp/circuit-check.py
```

Actual exit: `1`. Evidence: `qa-reports/evidence/vmhunter-circuit-before-expected-failure-20261124.log` and `qa-reports/evidence/vmhunter-circuit-before-expected-failure-20261124.json`.

### Restart regression after fix

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-lab-20261124/compose-durable.json run --rm -v /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/vmhunter-circuit-check-20261124.py:/tmp/circuit-check.py:ro proof python /tmp/circuit-check.py
```

Actual exit: `0`. Evidence: `qa-reports/evidence/vmhunter-circuit-after-20261124.log` and `qa-reports/evidence/vmhunter-circuit-after-20261124.json`.

