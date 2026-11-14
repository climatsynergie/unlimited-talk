# Incoming callbacks and client sheet — 14 November 2026

Scope: isolated QA branch `qa/full-audit-20261108`, based on325e9e081bed2dabd7fe1a5e46657a52bff0ee8b. No deployment, production database writes, call-control changes or real calls were performed.

## QA-22 — MEDIUM: incoming callers cannot be called from their client sheet

Confirmed: the follow-up detail API already returns the canonical imported profile, but the UI omits it and has no outgoing-call action. Incoming history renders plain text without an action to open the client. Chromium baseline regression fails because the client's email/address are absent. Manually copying a number into the workstation is the existing workaround.

The follow-up sheet now shows available coordinates and **Appeler ce client**. Incoming history offers **Voir la fiche client** for both calls with a linked follow-up and answered calls without one. Follow-ups retain their notes/status/history. A caller without an imported contact can be called using the visible number; no new contact or campaign is silently created. This change displays contact coordinates; it does not implement new campaign qualification/appointment creation for incoming-only contacts.

Outgoing calls reuse the existing global PhoneController, reservation endpoint, authentication, CSRF, recording and reporting. The reservation is manual; the server can link a known canonical contact by phone. Closing the sheet leaves active media running; the global phone bar remains available. The sheet also exposes **Raccrocher** and **Boîte vocale** during its outgoing call. An active call blocks a duplicate, and automatic chaining has an explicit pause action before calling manually. The UI displays reservation errors and permits retry.

**Ne pas contacter** remains blocked in both UI and the authoritative manual-call service. **Non intéressé** remains manually callable as previously requested. Hidden/invalid numbers cannot be dialed. Incoming history now includes two canonical restriction booleans in its existing queue-authorized read; no endpoint, database migration, permission expansion, routing or provider configuration changes. Stale client snapshots do not bypass server revalidation.

## Executed evidence

Raw synthetic fixtures/screenshots/traces remain ignored locally. Recorder metadata retains exact commands, UTC, source/diff hash, real exit and output hash. Counts below are scoped executions, not a line/branch coverage percentage. The browser suite mocks business HTTP/SDK boundaries; the separate API/PostgreSQL suite executes actual server/database code with simulated provider/media. No claim of real headset/PSTN acceptance.

| Check | Status | Exit | Result | Evidence |
|---|---|---|---|---|
| inbound-client-before | FAIL | 1 | Baseline: missing client coordinates reproduced in Chromium | [metadata](evidence/inbound-client-before.json), [log](evidence/inbound-client-before.log) |
| inbound-client-browser | FAIL | 1 | 10 PASS / 1 FAIL: new fixture polled SDK before asynchronous load | [metadata](evidence/inbound-client-browser.json), [log](evidence/inbound-client-browser.log) |
| inbound-client-release-browser | PASS | 0 | 27 PASS / 0 skipped: callback, history, DNC, NI, unknown caller, failure/retry, mobile/accessibility and surrounding phone flows | [metadata](evidence/inbound-client-release-browser.json), [log](evidence/inbound-client-release-browser.log) |
| inbound-client-unit | PASS | 0 | 159 controller/installed-SDK tests | [metadata](evidence/inbound-client-unit.json), [log](evidence/inbound-client-unit.log) |
| inbound-client-backend | PASS | 0 | 217 backend unit tests | [metadata](evidence/inbound-client-backend.json), [log](evidence/inbound-client-backend.log) |
| inbound-client-release-build | PASS | 0 | TypeScript/production frontend build | [metadata](evidence/inbound-client-release-build.json), [log](evidence/inbound-client-release-build.log) |
| inbound-client-release-format | PASS | 0 | Formatting | [metadata](evidence/inbound-client-release-format.json), [log](evidence/inbound-client-release-format.log) |
| inbound-client-real-api-postgres | PASS | 0 | Actual signed incoming HTTP/PG suite, canonical profile/restrictions, queue authorization, concurrency and recovery; provider/media simulated | [metadata](evidence/inbound-client-real-api-postgres.json), [log](evidence/inbound-client-real-api-postgres.log) |

The initial after-fix browser failure was a fixture race: it dereferenced `phoneProof.connections` before the SDK module had loaded following a rejected/resubmitted reservation. The assertion now polls zero until the SDK exists, then still requires exactly one connection and two reservation attempts. All errors and traces remain retained; no failing product assertion was removed. Mobile screenshot: `evidence/inbound-client-mobile.png`; axe WCAG2A/AA/2.1AA and horizontal-overflow assertions passed.

The real HTTP/PG suite asserts that queue outsiders receive403, history exposes current canonical profile/DNC/NI after a synthetic contact update, private recording permissions remain enforced, signed offers/replays and three-/twenty-agent **admission** stay correct. This is not twenty simultaneous real audio conversations. Local migration installed0012 into a new disposable PostgreSQL18.6 project with communications disabled; existing labs and managed deployments were untouched.

## Exact commands

### inbound-client-before: FAIL, exit 1

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=inbound-client-before npm --prefix frontend run test:browser -- tests/inbound-callback.spec.ts --grep 'la fiche affiche'
```

### inbound-client-browser: FAIL, exit 1

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=inbound-client QA_BROWSER_OBSERVATIONS=/home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/inbound-client-observations.jsonl npm --prefix frontend run test:browser -- tests/inbound-callback.spec.ts tests/incoming.spec.ts tests/incoming-session.spec.ts
```

### inbound-client-release-browser: PASS, exit 0

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=inbound-client-release QA_BROWSER_OBSERVATIONS=/home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/inbound-client-release-observations.jsonl npm --prefix frontend run test:browser -- tests/inbound-callback.spec.ts tests/incoming.spec.ts tests/incoming-session.spec.ts tests/phone.spec.ts
```

### inbound-client-unit: PASS, exit 0

```sh
npm --prefix frontend run test:phone
```

### inbound-client-backend: PASS, exit 0

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -e PYTHONDONTWRITEBYTECODE=1 -v /home/codexdev/unlimited-talk-qa-audit/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro -v /home/codexdev/unlimited-talk-qa-audit/scripts:/scripts:ro unlimited-talk-qa-audit:dependency-hardened python -m unittest discover -s /tests -p 'test_*.py' -v
```

### inbound-client-release-build: PASS, exit 0

```sh
npm --prefix frontend run build
```

### inbound-client-release-format: PASS, exit 0

```sh
npm --prefix frontend run format:check
```

### inbound-client-real-api-postgres: PASS, exit 0

```sh
env 'FOUNDATION_COMPOSE_ARGS=-p ut-inbound-client-20261114 -f /home/codexdev/unlimited-talk-qa-audit/compose.yaml -f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/inbound-client-20261114/compose.qa.yaml' FOUNDATION_TEST_URL=http://127.0.0.1:18314 python3 tests/verify_incoming_runtime.py
```

## Remaining boundaries

- Fresh complete Foundation CI, clean image publication/provenance and its migration/rollback/recovery gates are **NOT TESTED at report creation**; verify the exact published source before deployment. Earlier325e9e0 CI does not validate this patch.
- Live carrier/audio acceptance remains **BLOCKED** without the owner's controlled test; no real calls initiated.
- Broader native-library, complete disaster recovery and mixed20-agent audio/load gates remain open. Full production certification remains **NO-GO** per the broader audit; this operational UI correction does not close those gates.
- Deployment is the owner's normal manual workflow after CI publication. Agents must refresh after successful deployment to load the client-sheet changes.
