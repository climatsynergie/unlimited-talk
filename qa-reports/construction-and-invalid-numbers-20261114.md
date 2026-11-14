# Optional construction year and invalid-number pause — 14 November 2026

Scope: isolated QA branch `qa/full-audit-20261108`, based on `ce47ea5c9843d4607e4500e3113d2e75e9bc1b22`. The owner requested a free-text **optional** construction year and renewed investigation of invalid numbers interrupting automatic dialing. No production writes, service restart, deployment, call origination or call-control changes were performed for this work.

## Product changes and compatibility

`Année de construction` is a text input in the housing section. It accepts e.g. `Vers 1970`, `Inconnue`, or an omitted/empty value. It does not count toward required answers. Existing length/control-character and strict-string validation apply. Saving a qualification or appointment retains the answer in a versioned JSON snapshot.

Schema3 adds this optional key; schema1 and schema2 files remain byte-for-byte unchanged. New code reads historical versions, and a contact draft upgrades to3 without inventing answers or rewriting historical appointments. A historical appointment's version2 editor retains its version2 fields. A tab loaded before deployment must refresh before creating a new appointment: the existing current-schema creation guard rejects stale versions with422.

No SQL migration or permissions change is needed: database schema remains0012. Actual calendar and dialer HTTP/PostgreSQL gates passed against PostgreSQL18.6 and synthetic data. This is **not** a new execution of every populated-schema migration or predecessor rollback gate. Important semantic rollback boundary: older ce47ea5 code does not understand version3 writes/edits. JSON history is retained, but rolling back after new version3 saves requires a reader-compatible release/backport; do not downgrade snapshots or claim automatic old-binary edit compatibility.

## QA-21 — HIGH operational, reproduced and fixed: invalid destination pauses the queue

The pinned Twilio Voice SDK2.18.5 stores outgoing calls in `_activeCall`, while Device's error lookup searches incoming `_calls`. An outgoing31404 reaches Device.error without its optional Call, and the previous whitelist omitted it. Four destination codes13223/13224/13226/21211 arrive wrapped as SDK31000 with a numeric `originalError.code`. Real installed Device/Call lifecycle tests reproduced all five missing cases, with RTC/audio/signaling transport simulated and real network signaling prohibited.

The controller now reconciles31404 and only those exact bounded numeric nested destination codes. It does not infer from messages, string codes or general31000 errors. It waits for a server **finished** intent before the full ten-second delay and next contact. Database constraints require a consumed intent and parent call reference for finished. Expired/cancelled reservations do not prove a rejected destination and preserve the pause; this prevents an unconsumed/misconfigured Voice URL from cycling through contacts. Newer Stop and booking holds retain precedence. Authentication, microphone, WebSocket, unknown and genuine transport errors still pause. Nothing marks a customer permanently invalid, changes DNC/NI policy or deletes a number.

Primary provider references: [31404](https://www.twilio.com/docs/api/errors/31404), [13223](https://www.twilio.com/docs/api/errors/13223), [13224](https://www.twilio.com/docs/api/errors/13224), [13226](https://www.twilio.com/docs/api/errors/13226), [21211](https://www.twilio.com/docs/api/errors/21211). These describe provider error categories; they do not establish which error a live agent saw. Installed SDK source and executed lifecycle tests establish the wrapper/association behavior above.

## Evidence and executed checks

Each linked recorder JSON contains the full command, real process exit, UTC interval, source revision, working-diff hash and output hash. Raw logs and synthetic fixtures remain in ignored local evidence; no push-protection bypass. All commands below ran from `/home/codexdev/unlimited-talk-qa-audit`. Repeated executions are not added as distinct coverage. Browser cases use mock HTTP/SDK boundaries; the separate HTTP/PostgreSQL gates exercise the actual server and database. Neither is real PSTN/audio acceptance.

| Check | Status | Exit | Scope/result | Evidence |
|---|---|---|---|---|
| bad-number-actual-sdk-before | FAIL | 1 | 3 PASS / 1 FAIL; actual SDK31404 reproduces unwanted pause | [metadata](evidence/bad-number-actual-sdk-before.json), [log](evidence/bad-number-actual-sdk-before.log) |
| bad-number-wrapped-sdk-before | FAIL | 1 | 4 FAIL; actual SDK wraps destination errors in31000 | [metadata](evidence/bad-number-wrapped-sdk-before.json), [log](evidence/bad-number-wrapped-sdk-before.log) |
| construction-year-before | FAIL | 1 | 8 methods: 7 PASS / 1 ERROR before v3 support | [metadata](evidence/construction-year-before.json), [log](evidence/construction-year-before.log) |
| construction-bad-number-focused-browser | FAIL | 1 | 4 PASS / 1 FAIL; initial fixture expected an explicit empty optional key | [metadata](evidence/construction-bad-number-focused-browser.json), [log](evidence/construction-bad-number-focused-browser.log) |
| construction-bad-number-final-unit | PASS | 0 | 159 PASS / 0 skipped; controllers and real installed SDK | [metadata](evidence/construction-bad-number-final-unit.json), [log](evidence/construction-bad-number-final-unit.log) |
| construction-bad-number-final-backend | PASS | 0 | 217 PASS; isolated read-only runtime with current source mounted | [metadata](evidence/construction-bad-number-final-backend.json), [log](evidence/construction-bad-number-final-backend.log) |
| construction-bad-number-host | PASS | 0 | 23 PASS | [metadata](evidence/construction-bad-number-host.json), [log](evidence/construction-bad-number-host.log) |
| construction-bad-number-final-browser | PASS | 0 | 48 PASS; Chromium with isolated HTTP/SDK fixtures | [metadata](evidence/construction-bad-number-final-browser.json), [log](evidence/construction-bad-number-final-browser.log) |
| construction-bad-number-final-build | PASS | 0 | TypeScript and production frontend build | [metadata](evidence/construction-bad-number-final-build.json), [log](evidence/construction-bad-number-final-build.log) |
| construction-bad-number-final-format | PASS | 0 | Formatting | [metadata](evidence/construction-bad-number-final-format.json), [log](evidence/construction-bad-number-final-format.log) |
| construction-year-real-api-postgres | PASS | 0 | Actual HTTP/PostgreSQL calendar, optional year, snapshots, authorization/concurrent edits | [metadata](evidence/construction-year-real-api-postgres.json), [log](evidence/construction-year-real-api-postgres.log) |
| bad-number-real-api-postgres | PASS | 0 | Actual HTTP/PostgreSQL dialer; failed/no-answer keeps running | [metadata](evidence/bad-number-real-api-postgres.json), [log](evidence/bad-number-real-api-postgres.log) |
| construction-year-isolated-cleanup | PASS | 0 | Only synthetic project ut-construction-20261114 removed | [metadata](evidence/construction-year-isolated-cleanup.json), [log](evidence/construction-year-isolated-cleanup.log) |

The initial empty-year browser fixture expected `construction_year: ""` in the raw request even when an untouched optional input was omitted. Its corrected assertion accepts omission at that boundary and still verifies booking and the submitted answer; the actual API test separately requires persisted normalized `""`. No failing application test was removed. Initial temporary environment failures (missing pinned image, overlapping read-only mounts, disallowed transport port as APP_ORIGIN) are retained in `evidence/construction-year-isolated-*`. Only the isolated override was corrected; origin/security assertions were not loosened.

Read-only live observation at13:33:56UTC found ce47ea5 healthy, schema0012 and calling enabled. No `dialer.pause_cause.*` records were returned in the48-hour aggregate. This is not proof of no pauses or evidence that a particular live incident was31404. Investigation command: `evidence/bad-number-live-diagnostics-readonly.{json,log}`. No production customer records or credentials were collected.

## Commands

### bad-number-actual-sdk-before: FAIL, exit 1

```sh
node --experimental-strip-types --test '--test-name-pattern=actual SDK unassociated result' frontend/tests/phone-sdk.unit.cjs
```

### bad-number-wrapped-sdk-before: FAIL, exit 1

```sh
node --experimental-strip-types --test '--test-name-pattern=unassociated result (13223|13224|13226|21211)' frontend/tests/phone-sdk.unit.cjs
```

### construction-year-before: FAIL, exit 1

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -e PYTHONDONTWRITEBYTECODE=1 -v /home/codexdev/unlimited-talk-qa-audit/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro unlimited-talk-qa-audit:dependency-hardened python -m unittest discover -s /tests -p test_qualification.py -v
```

### construction-bad-number-focused-browser: FAIL, exit 1

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=construction-bad-number-focused QA_BROWSER_OBSERVATIONS=/home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/construction-bad-number-focused-observations.jsonl npm --prefix frontend run test:browser -- tests/autodialer.spec.ts --grep 'construction|v2 ouverte|device-not-found|ancien commentaire'
```

### construction-bad-number-final-unit: PASS, exit 0

```sh
npm --prefix frontend run test:phone
```

### construction-bad-number-final-backend: PASS, exit 0

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -e PYTHONDONTWRITEBYTECODE=1 -v /home/codexdev/unlimited-talk-qa-audit/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro -v /home/codexdev/unlimited-talk-qa-audit/scripts:/scripts:ro unlimited-talk-qa-audit:dependency-hardened python -m unittest discover -s /tests -p 'test_*.py' -v
```

### construction-bad-number-host: PASS, exit 0

```sh
python3 -m unittest discover -s tests/host -p 'test_*.py' -v
```

### construction-bad-number-final-browser: PASS, exit 0

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=construction-bad-number-final QA_BROWSER_OBSERVATIONS=/home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/construction-bad-number-final-observations.jsonl npm --prefix frontend run test:browser -- tests/autodialer.spec.ts tests/phone.spec.ts tests/incoming.spec.ts tests/incoming-session.spec.ts tests/calendar-reconfirmation.spec.ts
```

### construction-bad-number-final-build: PASS, exit 0

```sh
npm --prefix frontend run build
```

### construction-bad-number-final-format: PASS, exit 0

```sh
npm --prefix frontend run format:check
```

### construction-year-real-api-postgres: PASS, exit 0

```sh
env 'FOUNDATION_COMPOSE_ARGS=-p ut-construction-20261114 -f /home/codexdev/unlimited-talk-qa-audit/compose.yaml -f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/construction-year-20261114/compose.qa.yaml' FOUNDATION_TEST_URL=http://127.0.0.1:18314 python3 tests/verify_calendar.py
```

### bad-number-real-api-postgres: PASS, exit 0

```sh
env 'FOUNDATION_COMPOSE_ARGS=-p ut-construction-20261114 -f /home/codexdev/unlimited-talk-qa-audit/compose.yaml -f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/construction-year-20261114/compose.qa.yaml' FOUNDATION_TEST_URL=http://127.0.0.1:18314 python3 tests/verify_dialer.py
```

### construction-year-isolated-cleanup: PASS, exit 0

```sh
sudo -n docker compose --project-directory /home/codexdev/unlimited-talk-qa-audit -p ut-construction-20261114 -f compose.yaml -f qa-reports/evidence/construction-year-20261114/compose.qa.yaml down --volumes --remove-orphans
```

## Remaining validation / release status

- **PASS:** the explicitly executed local gates above, for their stated boundaries. No numerical line/branch coverage was collected for this change; test counts are not coverage percentages.
- **NOT TESTED at report creation:** fresh complete Foundation CI, clean release image/provenance, all migration/rollback/restore gates on this exact patch. Main/QA CI must supply their own result; previous ce47ea5 CI does not count.
- **BLOCKED without controlled acceptance:** real invalid destinations/provider behavior, headset/audio, carrier callback timing and simultaneous live agents. No calls were initiated. After deployment, agents must refresh their tabs and the owner should supervise acceptance.
- **OPEN:** earlier native-library, full recovery, mixed20-agent workload and real-carrier gates remain as recorded in the broader audit. This targeted patch does not close them.
- **Production certification: NO-GO** until the broader gates are resolved. Owner-authorized operational publication through normal main CI is distinct from full production certification. No deployment was performed by this audit.
