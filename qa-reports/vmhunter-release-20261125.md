# VM Hunter release integration — 25 November 2026

The owner authorized deploying both incoming appointment context and voicemail
screening code after stopping calls. Incoming context dc44e0f was deployed and
verified separately at 16:06 UTC (70 Python source hashes, READY schema12, manual
calling enabled). Original guard failures remain recorded in its isolated worktree.

The owner now explicitly approves the disclosed US processing and requests all
agents and contacts in CHIN LIST 514_REGION. They delegated the rollout choice.
Chosen approach: deploy the combined, tested code dormant; complete a controlled
human/voicemail audio check before enabling broad automatic hangups. No agent or
customer call is originated by these release tools. Dormant code installation
is not active filtering, a real telephony PASS, or overall production certification.

## Scope and maintained behavior

This integrates committed VM runtime 05a8809 with current live UI/API dc44e0f.
The incoming client-sheet/appointment features and prior telephony fixes remain.
Version 3 campaign policy explicitly opts into every active assigned agent and
current campaign contact, with authoritative membership/phone checks before
claiming and rejection. Version 1/2 pilot restrictions are unchanged. Manual,
incoming and other-campaign calls retain their existing paths. Two concurrent
analyses and finite 1–1000 budget remain; excess traffic connects normally.
No new schema or migration. Appended voice events are readable by prior schema12
code. Call-drain, deployment lock, OCI provenance, rollback and manual calling
restoration remain required. No operator guard is relaxed.

## Executed checks

Commands, actual exit codes, source diff fingerprints and SHA-verified logs are
in `evidence/vmhunter-release-20261125/validation-manifest.json` and each recorder
JSON/log. Local API source is mounted read-only over the canonical prior QA image;
this does not replace fresh exact-source main CI or cryptographic OCI proof.

- Unit suite: 305 tests PASS, exit 0.
- New campaign-scope regression: failed on the old pilot parser (ProtocolError),
  passed after explicit version-3 implementation; no assertion weakened.
- Signed HTTP/PostgreSQL/provider-loopback screening: PASS, exit 0; 22 synthetic
  analyses, safe results, actual expiry, two simultaneous jobs, manual pause/stop,
  campaign third-agent admission, exclusion/revocation, machine reporting and
  next-call continuation. Zero real calls. Not a real-agent capacity proof.
- Phone controller: 175 tests PASS, exit 0.
- Frontend build and formatting: PASS, exit 0.
- Chromium: 79 tests PASS, exit 0 (autodialer, incoming session, phone, incoming callbacks).
- Appointment context HTTP/PostgreSQL: 5 tests PASS, exit 0.
- Voice, dialer, inbound and incoming runtime HTTP/PostgreSQL checks PASS, exit 0.
  Incoming proof includes synthetic three-/20-agent concurrent admission.

Invocation failures are retained: an initial recorder argument was misordered
(exit127, no test run), and a coordinator referenced nonexistent
`tests/verify_incoming.py` (exit2, no incoming test run). Corrected actual inbound
and incoming-runtime checks executed successfully. Neither failure is reported
as an application defect or replaced by a fabricated PASS.

## Activation and residual risks

BLOCKED / not verified: real key classification, actual Twilio Streams permissions,
public WSS/media-track behavior, bilingual human/voicemail false positives, real
audio/recordings, greeting latency, metering and stream stop. A participating agent
and consenting phones are required. No real acceptance or live audio transfer is
claimed. Optional sidecar and public perimeter routes must be installed/reviewed
before activation; ordinary deployments do not activate them implicitly.

Inherited native Expat/OpenSSL findings in the preceding QA report remain open;
this release does not clear them or establish overall security GO. The packaged
OpenTelemetry API patch 1.45.2 is included. Full final CI/provenance/deployment and
post-release results will be appended only after execution.

Current status: combined code deployed and verified at 16:35 UTC; VM filtering
remains inactive. General production-readiness NO-GO remains separate from the
owner-authorized scoped operational release.


## Actual activation infrastructure preflight

Read-only discovery on the live API container completed with exit 0:
`python3 qa-reports/evidence/vmhunter-release-20261125/activation-preflight.py`
(evidence `vmhunter-real-runtime-preflight-corrected-20261125.*`). Its successful
exit means discovery executed, **not** that activation requirements passed.

- **BLOCKED:** verified TLS handshakes to both app.vmhunter.com and api.twilio.com
  timed out from the existing restricted API network. No credentials or audio
  were sent. Ordinary existing browser calls do not establish this new sidecar
  transport; opening the entire application network is not an acceptable shortcut.
- **NOT INSTALLED:** optional VM sidecar, API policy mount and explicit VM media /
  screening perimeter routes. Normal protected deployment is intentionally dormant.
- **PASS (storage only):** previously supplied key is stored root-private mode600.
  **NOT TESTED:** actual key/subscription/Streams permissions.
- **NOT TESTED:** real PSTN/audio/classification and multi-agent real acceptance.

The first discovery script contained a newline-escaping syntax error in its
remote wrapper (exit1, no conclusions); its failure log is preserved. The
corrected diagnostic returned the above infrastructure blockers. No secret
values, call audio, customer numbers or notes were exported.

Fresh limited security checks: npm production audit PASS exit0, zero advisories;
offline actual QA-image installed Python distribution inventory plus live OSV
query PASS exit0, 64 distributions, zero matches. They do **not** cover the
unresolved embedded Expat/psycopg OpenSSL native findings. Native versions remain
in the evidence inventory; no full-image security clearance is claimed.


## Approved inactive policy

The owner's explicit approvals and campaign-wide target were stored root-private
without modifying the application runtime or starting a call. The policy remains
`enabled=false`; no customer numbers/agent identities are copied into it.
Read-only campaign preflight confirmed an active campaign with 17 active assigned
agents and 15,842 active contacts at query time. These are counts, not a capacity
proof. The canonical disabled example is in deployment/vmhunter.

Evidence: `vmhunter-campaign-readonly-preflight-20261125.*` and
`vmhunter-approved-disabled-policy-corrected-20261125.*`, both exit0. An initial
nested-string newline error prevented the first policy wrapper from executing
(exit1); its log is retained. The corrected operation uses exclusive root-private
creation and refuses to replace a differing existing policy. No API mount,
public phone route, provider setting or call state was changed.


## Final operational release — completed, 16:35 UTC

- **PASS:** complete main Foundation CI and publication for
  `36a451a4e974dc0a8ff80bbe5540806f57fa3c6f`:
  [run 45652030628](https://github.com/climatsynergie/unlimited-talk/actions/runs/45652030628).
  Test job: 59 successful steps; publish job: 5 successful steps. Raw provider
  conclusions are in `evidence/vmhunter-release-20261125/ci-completed*.json`.
  These are observed GitHub conclusions, not separately exported runner exit codes.
- **PASS, exit0:** cryptographic OCI provenance, unchanged repo/workflow/ref/source
  policy and deny-self-hosted policy. Evidence: `vmhunter-release-provenance-20261125.*`.
- **PASS, exit0:** unchanged protected deployer installed the same tested image,
  retained call-drain/lock/rollback checks, and restored manual calling.
  Evidence: `vmhunter-release-deployment-20261125.*`.
- **PASS, exit0:** post-release verification confirms READY, schema12,
  `communications=manual`, `calling_enabled=true`, exact revision and all **73**
  Python source hashes. Existing client/appointment UI strings are present.
  Login HTTP200; unauthenticated histories HTTP401. Read-only compatibility query:
  20 recent calls, 5 matching appointments, 14.77ms; not a load benchmark.
  Evidence: `vmhunter-release-post-verify-20261125.*`.
- **PASS, exit0 (limited scope):** actual newly released image inspected offline
  on the server with network disabled; its 64 installed Python distributions
  returned zero OSV matches. OpenTelemetry API1.45.2 confirmed. Expat2.9.0 and
  psycopg-bundled OpenSSL3.5.7 remain; native findings are **not cleared**.
  Evidence: `vmhunter-released-image-python-osv-20261125.*` and the security JSONs.

Deployed immutable image:
`ghcr.io/climatsynergie/unlimited-talk-api@sha256:65bc7e7750006552d129a2466f13cfb7e589bd3f43f202b48f8414b03a6b825c`.
Preceding release dc44e0f remains the protected rollback target; no schema downgrade
was introduced or executed. No real call was initiated by QA/release tooling.

**Code deployment: completed. Active VM Hunter filtering: NOT ACTIVATED.**
The private approved campaign policy stays disabled and is not mounted in the
API. Dedicated constrained egress, optional sidecar, public media/signed-hook
routing, permissions/metering/cleanup verification and human audio acceptance
remain required. Normal calls and the incoming client/appointment UI are available.
See [controlled acceptance](vmhunter-acceptance-20261125.md).
Overall production certification and broad VM filtering remain **NO-GO**; this
is an explicitly authorized operational code release with recorded limitations.

## Exact executed commands and retained results

All commands ran from `/home/codexdev/unlimited-talk-vmhunter-release` unless
specified in the per-check JSON. Source-overlay tests and real network/media
limitations are described above. The manifest stores revision, working diff,
actual exit code and SHA256 of every retained log. A diagnostic discovery exit0
is not an activation PASS. Initial failures are retained.

### vmhunter-approved-disabled-policy-20261125

FAIL; actual exit `1`; log `qa-reports/evidence/vmhunter-approved-disabled-policy-20261125.log`.

```sh
python3 qa-reports/evidence/vmhunter-release-20261125/store-disabled-policy.py
```

### vmhunter-approved-disabled-policy-corrected-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-approved-disabled-policy-corrected-20261125.log`.

```sh
python3 qa-reports/evidence/vmhunter-release-20261125/store-disabled-policy.py
```

### vmhunter-campaign-readonly-preflight-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-campaign-readonly-preflight-20261125.log`.

```sh
python3 qa-reports/evidence/vmhunter-release-20261125/campaign-preflight.py
```

### vmhunter-campaign-scope-before-20261125

FAIL; actual exit `1`; log `qa-reports/evidence/vmhunter-campaign-scope-before-20261125.log`.

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -v /home/codexdev/unlimited-talk-vmhunter-release/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-vmhunter-release/tests:/tests:ro unlimited-talk-vmhunter-qa:committed python -m unittest discover -s /tests -p test_vmhunter_screen.py -v
```

### vmhunter-combined-appointments-pg-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-appointments-pg-20261125.log`.

```sh
env 'FOUNDATION_COMPOSE_ARGS=-f /home/codexdev/unlimited-talk-vmhunter-release/qa-reports/evidence/vmhunter-release-20261125/compose.json' FOUNDATION_TEST_URL=http://127.0.0.1:18138 GITHUB_SHA=dc44e0fcf4ed53e4e1026541ccecea90faa4901b python3 tests/verify_call_appointment_context.py
```

### vmhunter-combined-browser-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-browser-20261125.log`.

```sh
env 'FOUNDATION_COMPOSE_ARGS=-f /home/codexdev/unlimited-talk-vmhunter-release/qa-reports/evidence/vmhunter-release-20261125/compose.json' FOUNDATION_TEST_URL=http://127.0.0.1:18138 GITHUB_SHA=dc44e0fcf4ed53e4e1026541ccecea90faa4901b QA_EVIDENCE_MODE=vmhunter-combined-20261125 python3 tests/verify_browser.py autodialer.spec.ts incoming-session.spec.ts phone.spec.ts inbound-callback.spec.ts
```

### vmhunter-combined-dialer-pg-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-dialer-pg-20261125.log`.

```sh
/usr/bin/python3 tests/verify_dialer.py
```

### vmhunter-combined-format-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-format-20261125.log`.

```sh
npm run --prefix frontend format:check
```

### vmhunter-combined-inbound-pg-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-inbound-pg-20261125.log`.

```sh
/usr/bin/python3 tests/verify_inbound.py
```

### vmhunter-combined-incoming-pg-20261125

FAIL; actual exit `2`; log `qa-reports/evidence/vmhunter-combined-incoming-pg-20261125.log`.

```sh
/usr/bin/python3 tests/verify_incoming.py
```

### vmhunter-combined-incoming-runtime-pg-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-incoming-runtime-pg-20261125.log`.

```sh
/usr/bin/python3 tests/verify_incoming_runtime.py
```

### vmhunter-combined-lab-start-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-lab-start-20261125.log`.

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-release-20261125/compose.json run --rm migrate
```

### vmhunter-combined-lab-stop-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-lab-stop-20261125.log`.

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-release-20261125/compose.json stop api gateway objectstore db
```

### vmhunter-combined-lab-up-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-lab-up-20261125.log`.

```sh
sudo -n docker compose -f qa-reports/evidence/vmhunter-release-20261125/compose.json up -d --wait --wait-timeout 90 api objectstore gateway
```

### vmhunter-combined-npm-production-audit-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-npm-production-audit-20261125.log`.

```sh
npm audit --prefix frontend --omit=dev --json
```

### vmhunter-combined-observation-pg-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-observation-pg-20261125.log`.

```sh
/usr/bin/python3 tests/verify_vmhunter.py
```

### vmhunter-combined-phone-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-phone-20261125.log`.

```sh
npm run --prefix frontend test:phone
```

### vmhunter-combined-python-osv-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-python-osv-20261125.log`.

```sh
python3 qa-reports/evidence/vmhunter-release-20261125/security/inventory_python_image.py unlimited-talk-vmhunter-qa:committed
```

### vmhunter-combined-screen-pg-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-screen-pg-20261125.log`.

```sh
env 'FOUNDATION_COMPOSE_ARGS=-f /home/codexdev/unlimited-talk-vmhunter-release/qa-reports/evidence/vmhunter-release-20261125/compose.json' VMHUNTER_USE_LOCAL_SOURCE=1 python3 tests/verify_vmhunter_screen.py
```

### vmhunter-combined-unit-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-unit-20261125.log`.

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -v /home/codexdev/unlimited-talk-vmhunter-release/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-vmhunter-release/tests:/tests:ro -v /home/codexdev/unlimited-talk-vmhunter-release/scripts:/scripts:ro unlimited-talk-vmhunter-qa:committed python -m unittest discover -s /tests -p 'test_*.py' -v
```

### vmhunter-combined-voice-pg-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-voice-pg-20261125.log`.

```sh
/usr/bin/python3 tests/verify_voice.py
```

### vmhunter-combined-web-build-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-combined-web-build-20261125.log`.

```sh
npm run --prefix frontend build
```

### vmhunter-real-runtime-preflight-20261125

FAIL; actual exit `1`; log `qa-reports/evidence/vmhunter-real-runtime-preflight-20261125.log`.

```sh
python3 qa-reports/evidence/vmhunter-release-20261125/activation-preflight.py
```

### vmhunter-real-runtime-preflight-corrected-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-real-runtime-preflight-corrected-20261125.log`.

```sh
python3 qa-reports/evidence/vmhunter-release-20261125/activation-preflight.py
```

### vmhunter-release-deployment-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-release-deployment-20261125.log`.

```sh
python3 qa-reports/evidence/vmhunter-release-20261125/release-operator.py deploy
```

### vmhunter-release-idle-preflight-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-release-idle-preflight-20261125.log`.

```sh
python3 qa-reports/evidence/vmhunter-release-20261125/idle-preflight.py
```

### vmhunter-release-operators-prepared-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-release-operators-prepared-20261125.log`.

```sh
python3 qa-reports/evidence/vmhunter-release-20261125/prepare-operators.py
```

### vmhunter-release-post-verify-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-release-post-verify-20261125.log`.

```sh
python3 qa-reports/evidence/vmhunter-release-20261125/verify-live-release.py
```

### vmhunter-release-provenance-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-release-provenance-20261125.log`.

```sh
python3 qa-reports/evidence/vmhunter-release-20261125/release-operator.py prepare
```

### vmhunter-released-image-python-osv-20261125

PASS; actual exit `0`; log `qa-reports/evidence/vmhunter-released-image-python-osv-20261125.log`.

```sh
python3 qa-reports/evidence/vmhunter-release-20261125/security/inspect-released-image.py
```
