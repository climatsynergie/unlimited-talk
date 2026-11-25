# VM Hunter pre-agent screening — QA evidence and activation gates

Code revision: `05a88098516945cb6cd45a408f61c4eb8327c4f3`.
Branch: `qa/vmhunter-pilot-20261124` (pushed for Foundation CI only).
Image: `sha256:bad376d086483212951fedd395f5836dfeaaf95fd048e29c06ac51cc73a3311b`.
No merge into main, production deployment, Twilio route change, real telephone
call, real provider authentication or customer-audio transfer was performed.
All writes and external-service simulations used synthetic, isolated local data.
The production application is outside this change.

This supersedes the implementation gap in the historical
[observation report](vmhunter-observation-20261124.md). Version 1 observation is
retained. Version 2 implements the requested pre-agent message and optional
machine rejection; it is disabled by default and has not passed live acceptance.
See the [operator guide](../deployment/vmhunter/README.md).

## Delivered behavior

The private pilot matches CHIN LIST 514_REGION, selected agents AND consenting
numbers, with separate audio-processing and screening approvals. No selection
or approval was invented. Incoming/manual calls and unselected agents bypass it.
The optional overlay is not installed by the normal deployment workflow.
Scope/budget changes require a drained, controlled sidecar restart because its
policy is loaded at startup. Disabling the API policy prevents new dispatches
and releases pending decisions; it does not stop already admitted audio jobs.

The existing Dial/Number retains caller selection, recording, status callbacks,
maximum duration and completion. A signed Number whisper plays **« Bonjour, ici
Maisonverte Québec. Un conseiller vous répond dans un instant. »**. The agent
continues hearing ringing. Only explicit MACHINE/MACHINE or MACHINE/MACHINE_BEEP
results with confirmed stream cleanup and a fresh unchanged policy can reject.
Any uncertainty, caller DTMF, stale result, unavailable service or provider error
connects the ordinary call. No REST call creation/update/redirect is introduced.

Filtered machines use the existing voicemail disposition, excluded from answered
conversations/talk totals. They move to Pas de réponse only where no newer human
edit, appointment, callback or restriction takes precedence. The original
10-second wrap-up and voluntary pause/stop remain. Provider auth/quota cooldown
and durable orphan-stream protection bypass filtering without pausing agents.
Actual SDK rejection events and live timing still require telephone acceptance.

## Confirmed defects and repairs

| Finding | Severity / scope | Before and after evidence |
| --- | --- | --- |
| Late PSTN in-progress callback could override a machine rejection and mark the call answered before bridge. | High within the new, unreleased screening implementation; not evidence of a production incident. | `vmhunter-screen-end-to-end-red-20261124` actually failed, exit 1. Pending-screen handling now preserves rejection and releases only explicit continuation or stale recovery. The final built-image proof passes with reordered callbacks, correct metrics and next-call progression. |
| Missing screen-start during a transient DB outage could defer the answered state until termination, even after an ordinary bridge. | Medium, new pilot failure recovery; not a production incident. | `vmhunter-screen-missing-start-red-20261124` failed on committed 95d9f1d, exit 1. The answer/whisper window is now anchored durably at first observation. Final proof verifies recovery, no reopening on a delayed start, and screening after a genuinely long ringing period. |
| Installed opentelemetry-api 1.45.1 matched GHSA-mf5v-w3w3-f6cg / CVE-2026-126360. | Moderate dependency ReDoS; no exploitation demonstrated. | Fresh OSV inventory failed, exit 1. Lock upgraded to 1.45.2, image rebuilt, full 303-test suite passed and the 64-distribution OSV recheck returned zero matches, exit 0. |

Initial failures remain preserved. The first image build failed with local ENOSPC;
the recorded retry passed after cleanup of rebuildable package caches and unused
build artifacts. Synthetic red/green DBs were archived with verified gzip dumps
and SHA-256 manifests before their disposable volumes were removed. One legacy
Voice regression initially failed because the local fake object store was not
started; starting that existing test service and rerunning the unchanged test
passed. These harness failures were not hidden or relabelled as initial passes.

## Security status and remaining blockers

**NO-GO for production screening / real pilot activation.** Passing functional
checks does not clear these gates:

- **BLOCKED — native-library security:** the built image still embeds Expat 2.9.0.
  CVE-2026-113351 / 115506 / 117610 / 118370 remain in the upstream affected range;
  the CNA CVSS 4 scores are HIGH, while CVSS 3.1 rates 115506 HIGH and the other
  three MEDIUM. Application exploitability is not demonstrated. A patched build
  or a complete component/reachability disposition is required; APK upgrades
  alone do not replace Python's embedded copy.
- **BLOCKED — bundled OpenSSL review:** installed psycopg-binary 3.3.6 bundles
  OpenSSL 3.5.7 although stdlib TLS uses 3.5.9. The latest compatible 3.3.9 wheel
  was downloaded from official PyPI, SHA-256 verified and inspected offline: it
  also bundles 3.5.7. No ineffective driver upgrade was substituted for a fix.
  See [native-library review](native-library-review.md) for component scope.
- **BLOCKED — processing geography/consent:** published VM Hunter cloud terms
  state US hosting. The answer concerning Canada remains ambiguous. No customer
  audio was sent and no approval was inferred. The DPA also describes provider
  retention and model-improvement use unless the account opts out. Review those
  account choices before any pilot; no account setting was changed or support
  email sent. Our application not logging audio does not disable provider retention.
- **BLOCKED — controlled pilot inputs:** boss-selected agents and consenting test
  numbers are still required. The example is disabled and contains none.
- **NOT TESTED — live integrations:** real VM Hunter key validity, classification
  accuracy, allowance/billing; real Twilio Stream permissions, public WSS,
  track direction, TTS delay, SDK events, two-way audio and recording continuity.
- **NOT TESTED — real capacity/transfers:** two local synthetic agents do not
  establish 17–20-agent PSTN capacity or agent-transfer support.
- **BLOCKED — live agent transfers:** active audio transfer is not implemented
  in the reviewed app. English contact handoff and incoming re-offers are
  different workflows; no successful transfer acceptance is claimed.
- **NOT TESTED — live abrupt process loss:** durable gates are exercised locally;
  SIGKILL cannot clean up a real billed stream. Operators must inspect/stop it.
- **BLOCKED — deployment:** reviewed overlay/public routing, artifact provenance,
  resource/egress checks, call drain and explicit deployment authorization remain.

The Python OSV recheck covers installed distribution names/versions only. It
excludes vendored native libraries and does not establish exploitability. The
npm production audit also does not replace the native gate. No fresh Trivy/Grype
full-image scan was executed in this phase; no claim of a clean whole image is
made. Primary source refresh and inventory evidence are under
`evidence/vmhunter-screen-security-20261124/`, with before/after kept separately.

Primary records: [OpenTelemetry advisory](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-mf5v-w3w3-f6cg),
[Expat maintainer announcement](https://www.openwall.com/lists/oss-security/2026/11/02/6),
[official Python Alpine Dockerfile](https://github.com/docker-library/python/blob/master/3.12/alpine3.24/Dockerfile),
[VM Hunter API](https://vmhunter.com/docs/api), [DPA](https://vmhunter.com/dpa),
[Twilio Number whisper](https://www.twilio.com/docs/voice/twiml/number),
[Twilio voice/language table](https://www.twilio.com/docs/voice/twiml/say/text-speech).

## Coverage and rollback limits

No new line/branch coverage percentage was measured. The complete backend suite
contains 303 executed tests, including 57 VM Hunter/credential tests. New screen
contracts cover strict approval gates, exact campaign/agent/number intersection,
supported XML, immutable signatures/purpose/child binding, malformed responses,
HTTP refusal/redirect/size limits, safe DB failure handling, and preserving auth
rejections. Provider cooldown, cleanup and durable admission remain exercised.

The isolated signed HTTP → PostgreSQL → sidecar HTTP → synthetic Twilio/VM Hunter
WebSockets → signed result → completion/reporting proof covers 19 safe decision
cases and 20 fake analyses, including two concurrent agents, actual eight-second
expiry, caller input, later human edits, manual pause/stop, silence, ambiguity,
quota/auth errors, unavailable sidecar and unconfirmed cleanup. It initiates
**zero real calls**. Browser suites exercise real Chromium with mocked provider
and API responses; they do not certify real PSTN audio or VM classification.
The three focused browser suites passed **52/52**, including the newly added
pre-bridge-machine rejection/next-call case. Phone/controller units passed
**175/175**. There is no inferred pass for real audio or live classifiers.

Schema stays at `0012_incoming_runtime`; no new table, migration or destructive
schema downgrade is needed. An earlier green snapshot was restored into separate
tmpfs PostgreSQL and 17 histories were checked. After the final recovery fix, a
fresh migrated fixture was exercised, then exact preceding c93d2d1 app sources,
verified against Git, read 25 screened histories including the waiting marker in
a read-only transaction. Schema/voice-intent/event fingerprints stayed identical;
the final fixture was archived with SHA-256. This is source read compatibility on
current dependencies, **not a boot of the previous image**. Full Foundation CI
separately exercises its existing preceding-image rollback, additive migrations,
backup/restore and database-outage recovery checks.

To roll back the optional feature, disable the private policy, drain pending
analyses/calls, verify Twilio has no orphan streams, stop the optional sidecar and
only then change the application artifact. Preserve new append-only events.
Do not downgrade schemas or interrupt active agents to test rollback.

## Controlled real-call acceptance plan — not yet executed

1. Obtain processing approval and explicit call authorization; choose one agent
   and consenting phones. Verify the disabled policy, budget and kill switch.
2. Call a French/Québécois live person, an English person, voicemail with/without
   beep, silent answer and a screening assistant. Independently label each.
3. Listen to the Maisonverte greeting and both audio directions. Measure actual
   greeting/bridge delay; inspect a complete recording and browser SDK events.
4. Confirm voicemail reporting excludes talk/answered, uncertain answers reach
   the agent, no-answer/bad-number calls continue, and pause/stop still work.
5. Repeat with two agents concurrently, including an ordinary manual outgoing
   call and an incoming call with reception enabled. Active audio transfer is
   currently unsupported: mark that acceptance case BLOCKED, not PASS.
6. With approval, simulate provider unavailability and verify normal calls remain
   available, streams stop and metering/budget agree. Restore the disabled policy
   and prove the rollback path before opening a customer-list pilot.

For every call capture intent/call references, human label, predicted label,
actual decision, delay, audio, recording, stream cleanup, next-call progression
and usage. Stop for a human wrongly rejected, lost audio, auto-pause, orphan
stream, unacceptable delay or unexplained usage. No live accuracy percentage or
promised two-second detection is supported by the current evidence.

## Executed checks and exact commands

All logs and recorder JSON below are under `qa-reports/evidence/`. The manifest
`vmhunter-screen-validation-manifest-20261124.json` verifies each log SHA-256.
Pre-fix/early source-mounted runs preceded commit 95d9f1d; the final built-image
runs verify the committed source, without app-source mounts. Recorder diff hashes
are not claimed to fingerprint untracked files from those earlier runs.

| Executed check | Result | Exit | Recorder revision | Evidence basename |
| --- | --- | --- | --- | --- |
| Initial candidate image, recorded first attempt | FAIL | 1 | `95d9f1d` | `vmhunter-screen-release-image-20261124` |
| Initial candidate image, actual retry | PASS | 0 | `95d9f1d` | `vmhunter-screen-release-image-retry-20261124` |
| Initial candidate image label and all 72 app sources | PASS | 0 | `95d9f1d` | `vmhunter-screen-image-identity-20261124` |
| Initial candidate backend built-image suite: 303 tests | PASS | 0 | `95d9f1d` | `vmhunter-screen-built-backend-20261124` |
| Original pre-fix reordered-status reproduction | FAIL | 1 | `6372d77` | `vmhunter-screen-end-to-end-red-20261124` |
| Initial candidate signed pre-bridge/PG/socket/reporting proof | PASS | 0 | `95d9f1d` | `vmhunter-screen-built-prebridge-proof-20261124` |
| Previous source read/schema compatibility, synthetic restore | PASS | 0 | `95d9f1d` | `vmhunter-screen-rollback-read-20261124` |
| Initial candidate browser regression: 52 tests | PASS | 0 | `95d9f1d` | `vmhunter-screen-browser-regressions-20261124` |
| Phone/controller units: 175 tests | PASS | 0 | `95d9f1d` | `vmhunter-screen-final-phone-units-20261124` |
| Frontend formatting | PASS | 0 | `95d9f1d` | `vmhunter-screen-final-format-20261124` |
| Legacy Voice API, first harness attempt | FAIL | 1 | `95d9f1d` | `vmhunter-screen-legacy-voice-api-20261124` |
| Legacy Voice API, object store running | PASS | 0 | `95d9f1d` | `vmhunter-screen-legacy-voice-api-retry-20261124` |
| Legacy incoming API | PASS | 0 | `95d9f1d` | `vmhunter-screen-legacy-incoming-api-20261124` |
| Legacy automatic dialer API | PASS | 0 | `95d9f1d` | `vmhunter-screen-legacy-dialer-api-20261124` |
| Python distribution OSV before patch | FAIL | 1 | `6372d77` | `vmhunter-screen-python-security-20261124` |
| Python distribution OSV on rebuilt image | PASS | 0 | `95d9f1d` | `vmhunter-screen-python-security-after-20261124` |
| Production npm audit | PASS | 0 | `6372d77` | `vmhunter-screen-npm-security-20261124` |
| Latest Psycopg wheel native inspection, not remediation | PASS | 0 | `6372d77` | `vmhunter-screen-psycopg-native-candidate-20261124` |
| Primary security-source refresh | PASS | 0 | `6372d77` | `vmhunter-screen-security-primary-refresh-20261124` |
| Missing-start DB outage before correction | FAIL | 1 | `95d9f1d` | `vmhunter-screen-missing-start-red-20261124` |
| Missing-start recovery and long-ringing source proof | PASS | 0 | `95d9f1d` | `vmhunter-screen-answer-window-green-20261124` |
| Final committed release image | PASS | 0 | `05a8809` | `vmhunter-screen-final-release-image-20261124` |
| Final image label and 72 source hashes | PASS | 0 | `05a8809` | `vmhunter-screen-final-image-identity-20261124` |
| Final built-image backend: 303 tests | PASS | 0 | `05a8809` | `vmhunter-screen-final-built-backend-20261124` |
| Final signed screening/recovery proof: 19 cases, two agents | PASS | 0 | `05a8809` | `vmhunter-screen-final-built-prebridge-proof-20261124` |
| Final schema/source rollback: 25 histories and unchanged fingerprints | PASS | 0 | `05a8809` | `vmhunter-screen-final-schema-rollback-20261124` |
| Final Chromium regressions: 52 tests | PASS | 0 | `05a8809` | `vmhunter-screen-final-browser-regressions-20261124` |
| Final phone/controller regressions: 175 tests | PASS | 0 | `05a8809` | `vmhunter-screen-complete-phone-units-20261124` |
| Final ordinary outgoing API | PASS | 0 | `05a8809` | `vmhunter-screen-final-legacy-voice-api-20261124` |
| Final ordinary incoming API | PASS | 0 | `05a8809` | `vmhunter-screen-final-legacy-incoming-api-20261124` |
| Final ordinary automatic dialer API | PASS | 0 | `05a8809` | `vmhunter-screen-final-legacy-dialer-api-20261124` |
| Final built-image Python OSV scan | PASS | 0 | `05a8809` | `vmhunter-screen-python-security-final-20261124` |
| Final Foundation CI metadata verification | PASS | 0 | `05a8809` | `vmhunter-screen-final-foundation-ci-status-20261124` |

Commands ran from `/home/codexdev/unlimited-talk-qa-audit`. Each evidence JSON
also records revision, timing, command array and log hash. For the final proof,
`FOUNDATION_COMPOSE_ARGS` selected the local `compose-screen-built.json`; no
`VMHUNTER_USE_LOCAL_SOURCE` was set. The browser used the same compose config,
`FOUNDATION_TEST_URL=http://127.0.0.1:18135`,
`GITHUB_SHA=05a88098516945cb6cd45a408f61c4eb8327c4f3` and
`QA_EVIDENCE_MODE=vmhunter-screen-final-20261124`. All credentials were synthetic.

### Initial candidate image, recorded first attempt

FAIL; actual exit `1`. Log: `qa-reports/evidence/vmhunter-screen-release-image-20261124.log`.

```sh
sudo -n docker build --build-arg GIT_REVISION=95d9f1d15bed8c48a7be39014e0fd57881a1f470 -t unlimited-talk-vmhunter-qa:committed .
```

### Initial candidate image, actual retry

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-release-image-retry-20261124.log`.

```sh
sudo -n docker build --build-arg GIT_REVISION=95d9f1d15bed8c48a7be39014e0fd57881a1f470 -t unlimited-talk-vmhunter-qa:committed .
```

### Initial candidate image label and all 72 app sources

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-image-identity-20261124.log`.

```sh
python3 qa-reports/evidence/vmhunter-screen-image-identity-check-20261124.py
```

### Initial candidate backend built-image suite: 303 tests

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-built-backend-20261124.log`.

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro -v /home/codexdev/unlimited-talk-qa-audit/scripts:/scripts:ro unlimited-talk-vmhunter-qa:committed python -m unittest discover -s /tests -p 'test_*.py' -v
```

### Original pre-fix reordered-status reproduction

FAIL; actual exit `1`. Log: `qa-reports/evidence/vmhunter-screen-end-to-end-red-20261124.log`.

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-lab-20261124/compose-screen-red.json run --rm proof
```

### Initial candidate signed pre-bridge/PG/socket/reporting proof

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-built-prebridge-proof-20261124.log`.

```sh
python3 tests/verify_vmhunter_screen.py
```

### Previous source read/schema compatibility, synthetic restore

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-rollback-read-20261124.log`.

```sh
python3 qa-reports/evidence/vmhunter-screen-rollback-harness-20261124.py
```

### Initial candidate browser regression: 52 tests

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-browser-regressions-20261124.log`.

```sh
python3 tests/verify_browser.py autodialer.spec.ts incoming-session.spec.ts phone.spec.ts
```

### Phone/controller units: 175 tests

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-final-phone-units-20261124.log`.

```sh
npm run --prefix frontend test:phone
```

### Frontend formatting

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-final-format-20261124.log`.

```sh
npm run --prefix frontend format:check
```

### Legacy Voice API, first harness attempt

FAIL; actual exit `1`. Log: `qa-reports/evidence/vmhunter-screen-legacy-voice-api-20261124.log`.

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-lab-20261124/compose-screen-built.json run --rm -e VMHUNTER_PILOT_FILE=/not-present proof python /tests/voice-integration.py
```

### Legacy Voice API, object store running

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-legacy-voice-api-retry-20261124.log`.

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-lab-20261124/compose-screen-built.json run --rm -e VMHUNTER_PILOT_FILE=/not-present proof python /tests/voice-integration.py
```

### Legacy incoming API

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-legacy-incoming-api-20261124.log`.

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-lab-20261124/compose-screen-built.json run --rm proof python /tests/incoming-integration.py
```

### Legacy automatic dialer API

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-legacy-dialer-api-20261124.log`.

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-lab-20261124/compose-screen-built.json run --rm -e VMHUNTER_PILOT_FILE=/not-present proof python -c 'import json; QUALIFICATION=json.load(open("/tests/qualification-fixture.json")); exec(compile(open("/tests/dialer-integration.py").read(),"/tests/dialer-integration.py","exec"))'
```

### Python distribution OSV before patch

FAIL; actual exit `1`. Log: `qa-reports/evidence/vmhunter-screen-python-security-20261124.log`.

```sh
python3 qa-reports/evidence/vmhunter-screen-security-20261124/inventory_python_image.py unlimited-talk-vmhunter-qa:committed
```

### Python distribution OSV on rebuilt image

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-python-security-after-20261124.log`.

```sh
python3 qa-reports/evidence/vmhunter-screen-security-20261124/after/inventory_python_image.py unlimited-talk-vmhunter-qa:committed
```

### Production npm audit

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-npm-security-20261124.log`.

```sh
npm audit --prefix frontend --omit=dev --json
```

### Latest Psycopg wheel native inspection, not remediation

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-psycopg-native-candidate-20261124.log`.

```sh
sudo -n docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges -v /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/vmhunter-screen-security-20261124/psycopg-3.3.9-native:/candidate:ro unlimited-talk-vmhunter-qa:committed python -c 'import ctypes,glob,json; p=glob.glob("/candidate/psycopg_binary.libs/libssl-*.so.3")[0]; lib=ctypes.CDLL(p); lib.OpenSSL_version.argtypes=[ctypes.c_int]; lib.OpenSSL_version.restype=ctypes.c_char_p; print(json.dumps({"candidate":"psycopg-binary 3.3.9","openssl":lib.OpenSSL_version(0).decode()}))'
```

### Primary security-source refresh

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-security-primary-refresh-20261124.log`.

```sh
python3 qa-reports/evidence/vmhunter-screen-security-20261124/fetch_primary.py
```

### Missing-start DB outage before correction

FAIL; actual exit `1`. Log: `qa-reports/evidence/vmhunter-screen-missing-start-red-20261124.log`.

```sh
python3 tests/verify_vmhunter_screen.py
```

### Missing-start recovery and long-ringing source proof

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-answer-window-green-20261124.log`.

```sh
python3 tests/verify_vmhunter_screen.py
```

### Final committed release image

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-final-release-image-20261124.log`.

```sh
sudo -n docker build --build-arg GIT_REVISION=05a88098516945cb6cd45a408f61c4eb8327c4f3 -t unlimited-talk-vmhunter-qa:committed .
```

### Final image label and 72 source hashes

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-final-image-identity-20261124.log`.

```sh
python3 qa-reports/evidence/vmhunter-screen-final-image-identity-check-20261124.py
```

### Final built-image backend: 303 tests

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-final-built-backend-20261124.log`.

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro -v /home/codexdev/unlimited-talk-qa-audit/scripts:/scripts:ro unlimited-talk-vmhunter-qa:committed python -m unittest discover -s /tests -p 'test_*.py' -v
```

### Final signed screening/recovery proof: 19 cases, two agents

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-final-built-prebridge-proof-20261124.log`.

```sh
python3 tests/verify_vmhunter_screen.py
```

### Final schema/source rollback: 25 histories and unchanged fingerprints

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-final-schema-rollback-20261124.log`.

```sh
python3 qa-reports/evidence/vmhunter-screen-final-rollback-harness-20261124.py
```

### Final Chromium regressions: 52 tests

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-final-browser-regressions-20261124.log`.

```sh
python3 tests/verify_browser.py autodialer.spec.ts incoming-session.spec.ts phone.spec.ts
```

### Final phone/controller regressions: 175 tests

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-complete-phone-units-20261124.log`.

```sh
npm run --prefix frontend test:phone
```

### Final ordinary outgoing API

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-final-legacy-voice-api-20261124.log`.

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-lab-20261124/compose-screen-built.json run --rm -e VMHUNTER_PILOT_FILE=/not-present proof python /tests/voice-integration.py
```

### Final ordinary incoming API

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-final-legacy-incoming-api-20261124.log`.

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-lab-20261124/compose-screen-built.json run --rm proof python /tests/incoming-integration.py
```

### Final ordinary automatic dialer API

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-final-legacy-dialer-api-20261124.log`.

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-lab-20261124/compose-screen-built.json run --rm -e VMHUNTER_PILOT_FILE=/not-present proof python -c 'import json; QUALIFICATION=json.load(open("/tests/qualification-fixture.json")); exec(compile(open("/tests/dialer-integration.py").read(),"/tests/dialer-integration.py","exec"))'
```

### Final built-image Python OSV scan

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-python-security-final-20261124.log`.

```sh
python3 qa-reports/evidence/vmhunter-screen-security-20261124/after-final/inventory_python_image.py unlimited-talk-vmhunter-qa:committed
```

### Final Foundation CI metadata verification

PASS; actual exit `0`. Log: `qa-reports/evidence/vmhunter-screen-final-foundation-ci-status-20261124.log`.

```sh
python3 qa-reports/evidence/vmhunter-screen-ci-final-check-20261124.py
```


## Complete Foundation CI on the final code revision

**PASS — GitHub conclusion:** [run 45512050358](https://github.com/climatsynergie/unlimited-talk/actions/runs/45512050358),
source `05a88098516945cb6cd45a408f61c4eb8327c4f3`, QA branch. The test job
completed successfully with 56 successful steps; the publication job was skipped.
No main merge, registry publication or deployment occurred. The preceding
95d9f1d full run also completed successfully; the final run includes the additional
missing-start/late-start/long-ringing regression assertions.

The committed [.github/workflows/ci.yml](../.github/workflows/ci.yml) contains the
exact executed build, unit, populated migration, identity/permission, import/queue,
CRM/calendar/callback, telephony, reporting, complete browser, real browser/API/PG,
compatibility rollback, backup/restore and outage-recovery commands. It includes
`python3 tests/verify_vmhunter_screen.py` against a freshly built image without
local app-source overlays. These conclusions do not establish real carrier audio.

Raw run/job/step responses are preserved in
`evidence/vmhunter-screen-foundation-ci-final-20261124.json`. The public raw job-log
request returned HTTP 403 (**BLOCKED**). GitHub metadata exposes conclusions, not
individual process exit codes; none were invented. The separate metadata verifier
command returned actual exit 0, recorded in `vmhunter-screen-final-foundation-ci-status-20261124.*`.
Local commands above retain actual process exits and test counts.

**Release decision remains NO-GO for activation.** Functional CI success does
not clear embedded native libraries, cloud-processing approval, pilot selection,
actual WSS/key permissions or human telephone acceptance. The detailed plan and
remaining blockers above are the required next steps.
