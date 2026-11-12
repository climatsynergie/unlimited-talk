# Automatic pause follow-up — 12 November 2026

Base/deployed revision: `7105909a1129f5468b654a54f8d9eb17fc463d7b`. Work remains on isolated branch `qa/full-audit-20261108`. This follow-up does not merge, deploy, restart services, originate calls, change call controls or mutate production data.

## What the live evidence establishes

A read-only audit at **21:48:21 UTC**, covering 12 November in `America/Toronto`, matched the agent identified by the user. It observed 79 `dialer.pause` and 80 `dialer.start` actions that day. These include explicit browser requests; the audit did not distinguish human clicks from SDK-driven requests. The new release had deployed at **21:28:54 UTC** and was healthy with calling enabled. Three pauses were recorded after that deployment:

| Pause UTC (Toronto) | Closest call/result | Observed relationship |
|---|---|---|
| 21:40:33 (16:40:33) | Busy | Pause approximately 0.23 seconds after the terminal result |
| 21:44:18 (16:44:18) | Completed | Pause approximately 4.84 seconds after the terminal result |
| 21:46:57 (16:46:57) | No new reservation | Start at 21:46:53, failed `/next`, then pause |

No `dialer.pause_automatic` action was recorded for that agent in this audit window. Consequently these observed pauses are not the backend's explicit expired-presence/booking path. Server audit alone cannot prove whether an agent clicked Pause, nor which SDK code a tab received, nor which frontend bundle that tab had loaded.

The gateway recorded **one `/api/telephony/dialer/next` HTTP500** in the 21:46 minute. The API's privacy-preserving error record identifies `OperationalError` and **3314.1 ms**, followed by missing-intent404s. This aligns with the observed start/pause sequence. The old trace retained only the ten deepest SQLAlchemy frames, so it does **not** establish the failing application query or driver SQLSTATE. A three-second database timeout is plausible, not confirmed as the root cause. No production timeout or pool setting was increased.

Read-only executed commands and outputs: `evidence/charlotte-autopause-today-readonly.{json,log}`, `evidence/charlotte-autopause-gateway-status-readonly.{json,log}`, `evidence/charlotte-autopause-api-structured-readonly.{json,log}`. Sanitized remote scripts are retained in the ignored incident evidence directory. No customer numbers, credentials, SQL parameters or error messages were collected.

## Confirmed defects reproduced and repaired in QA

**QA-18 — HIGH: outgoing SDK errors have no associated Call.** The first fix incorrectly relied on the SDK supplying its optional Call argument. The installed SDK2.18.5 puts outgoing calls in `_activeCall`, while `_findCall` searches incoming `_calls`. A real SDK outgoing31486 therefore arrives at Device.error with no Call argument. The same regression with the real Device and Call classes fails on deployed7105909 (3PASS/1FAIL) and passes on the candidate (4PASS). Only RTC/microphone/transport/publishing/statistics are simulated; no provider connection occurs.

The candidate reconciles the explicit remote SIP results31480/31486/31603 even when the optional Call is absent. Server terminal confirmation still precedes the ten-second delay and another call. Generic31005 is deliberately **not** treated as a carrier result: the installed SDK also maps a genuine WebSocket53000 into31005 and retains its nested original error. Unknown/no-code, authentication, microphone and transport failures remain protected. The added SDK regression verifies that genuine WebSocket failures still pause.

**QA-19 — HIGH operational: one transient `/next` failure permanently pauses the browser queue.** Before the fix, all six tested transient statuses and the lost-response-after-commit case pause immediately. The candidate retries only network-status0,429,500,502,503,504; at most two retries, after two and four seconds. Every attempt reuses the **same UUID, browser ID and dialer generation**, before any SDK setup. Persistent failures still pause. Permission/ownership/business4xx do not retry. Pause/Stop/booking/disposal supersede the pending retry. The backend's existing same-ID replay integration assertion already covers a reserved intent replay before authorization.

This is a recovery repair, **not a claim that the underlying production database error has been repaired**. Persistent database failures remain a blocker to uninterrupted dialing. New diagnostics are needed to identify the actual SQLSTATE and application query site safely if the incident recurs.

**QA-20 — MEDIUM: a late `/next` rejection can override a newer Stop or booking hold.** Three before regressions record1PASS/2FAIL. The candidate's catch only pauses its still-armed, unchanged automatic epoch. Newer user actions remain authoritative. It preserves the previously tested SDK late-event ordering, booking, presence and lifecycle protections.

## Diagnostics and compatibility

- Pause control accepts optional enum `pause_cause` and bounded strict-integer `failure_code`; no free-text error, token, destination or customer field. Old clients remain valid. Successful control/authentication precedes diagnostic recording. An additional `dialer.pause_cause.*` audit fact preserves the original `dialer.pause` fact and exact reporting counts. These are **client-reported diagnostics**, not trusted security evidence.
- A newer tab facing the old backend validator after rollback retries a422 diagnostic pause once using the legacy body, with the same browser/generation and unchanged epoch. A newer Stop prevents that fallback. Before/after compatibility regressions are retained.
- API exception records retain existing bounded generic frames and add up to ten application-relative frames, plus a validated five-character SQLSTATE only for DBAPIError. SQL, bind parameters, messages, credentials and customer fields remain excluded. Deep-trace and privacy regressions fail before the diagnostic change and pass after it.
- No schema or database permissions change. Existing append-only audit storage is reused. Populated database migrations/rollback and real HTTP/PG regression gates are **NOT RERUN locally in this follow-up**; the new QA CI must verify them. Fresh local browser tests use isolated HTTP/SDK fixtures; do not describe them as real telephony acceptance.

## Reproduction and validation boundaries

The ten initial controller regressions for unassociated carrier results and transient/lost responses failed before repair. The actual-SDK baseline failed independently. All failed and intermediate evidence is retained. An initial focused browser run had3 failures because the new tests used `getByLabel` instead of the existing accessible combobox role selector; this was a **harness defect**, not a production failure. The corrected focused run passed4/4. No assertion was weakened or test removed.

`frontend/tests/phone-sdk.unit.cjs` is now included in `npm run test:phone` and will run in CI. It uses real SDK Device/Call lifecycle methods and fails closed if a real signaling stream is requested. Generated fixture IDs/tokens are synthetic. Browser fake media and the provider boundary remain simulated.

**Remaining limits:** precise SDK codes and frontend bundle loaded by the affected tab were not recorded historically; exact database-error root cause remains unconfirmed; genuine network/transport failures can still require an explicit resume; new QA full CI and live carrier acceptance are pending. Previous broader native-library/recovery release risks are unchanged. No claim of production certification or complete incident closure is made.

## Executed commands and evidence

Each recorder JSON below contains the actual command, process exit, UTC time, log SHA256 and source/diff identity. API/read-only command success is a successful investigation command, not a test that production dialing works. Final validation results are appended below.

| Check | Status | Exit | Result | Evidence |
|---|---|---|---|---|
| Before: unassociated carrier/next recovery | FAIL | 1 | 10 FAIL | [metadata](evidence/charlotte-autopause-unassociated-and-next-before.json), [log](evidence/charlotte-autopause-unassociated-and-next-before.log) |
| Before: late request precedence | FAIL | 1 | 1 PASS, 2 FAIL | [metadata](evidence/charlotte-autopause-stale-next-before.json), [log](evidence/charlotte-autopause-stale-next-before.log) |
| Before: diagnostic validation | FAIL | 1 | 2 PASS, 1 ERROR | [metadata](evidence/charlotte-pause-diagnostics-before.json), [log](evidence/charlotte-pause-diagnostics-before.log) |
| Before: rollback body | FAIL | 1 | 1 PASS, 1 FAIL | [metadata](evidence/charlotte-pause-rollback-body-before.json), [log](evidence/charlotte-pause-rollback-body-before.log) |
| Final controller and actual SDK | PASS | 0 | 140 PASS, zero skipped | [metadata](evidence/charlotte-final-controller.json), [log](evidence/charlotte-final-controller.log) |
| Final backend | PASS | 0 | 215 PASS | [metadata](evidence/charlotte-final-backend.json), [log](evidence/charlotte-final-backend.log) |
| Final host tools | PASS | 0 | 23 PASS | [metadata](evidence/charlotte-final-host.json), [log](evidence/charlotte-final-host.log) |
| Final TypeScript/build | PASS | 0 | PASS | [metadata](evidence/charlotte-final-build.json), [log](evidence/charlotte-final-build.log) |
| Final format | PASS | 0 | PASS | [metadata](evidence/charlotte-final-format.json), [log](evidence/charlotte-final-format.log) |
| Final browser | PASS | 0 | 41 PASS | [metadata](evidence/charlotte-final-browser.json), [log](evidence/charlotte-final-browser.log) |

All commands ran in `/home/codexdev/unlimited-talk-qa-audit`. Browser tests used a production build served by `npm exec -- vite preview --host 127.0.0.1 --port 15174 --strictPort` from `frontend/`.

### Before: unassociated carrier/next recovery — FAIL, exit 1

```sh
node --experimental-strip-types --test '--test-name-pattern=résultat opérateur|échec temporaire next|réponse perdue après réservation' frontend/tests/phone-controller.unit.ts
```

### Before: late request precedence — FAIL, exit 1

```sh
node --experimental-strip-types --test '--test-name-pattern=refus tardif next' frontend/tests/phone-controller.unit.ts
```

### Before: diagnostic validation — FAIL, exit 1

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -e PYTHONDONTWRITEBYTECODE=1 -v /home/codexdev/unlimited-talk-qa-audit/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro unlimited-talk-qa-audit:dependency-hardened python -m unittest discover -s /tests -p test_dialer_pause_diagnostics.py -v
```

### Before: rollback body — FAIL, exit 1

```sh
node --experimental-strip-types --test '--test-name-pattern=retour à une ancienne API|validation ancienne tardive' frontend/tests/phone-controller.unit.ts
```

### Final controller and actual SDK — PASS, exit 0

```sh
npm --prefix frontend run test:phone
```

### Final backend — PASS, exit 0

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -e PYTHONDONTWRITEBYTECODE=1 -v /home/codexdev/unlimited-talk-qa-audit/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro -v /home/codexdev/unlimited-talk-qa-audit/scripts:/scripts:ro unlimited-talk-qa-audit:dependency-hardened python -m unittest discover -s /tests -p 'test_*.py' -v
```

### Final host tools — PASS, exit 0

```sh
python3 -m unittest discover -s tests/host -p 'test_*.py' -v
```

### Final TypeScript/build — PASS, exit 0

```sh
npm --prefix frontend run build
```

### Final format — PASS, exit 0

```sh
npm --prefix frontend run format:check
```

### Final browser — PASS, exit 0

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=charlotte-final QA_BROWSER_OBSERVATIONS=/home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/charlotte-final-observations.jsonl npm --prefix frontend run test:browser -- tests/autodialer.spec.ts tests/phone.spec.ts tests/incoming.spec.ts tests/incoming-session.spec.ts
```

Additional SDK baseline proof: [commands and boundaries](evidence/charlotte-autopause-20261112/sdk-regression-results.md). The identical four-test suite recorded3PASS/1FAIL on7105909 and4PASS on the candidate. Request-metadata diagnostics: [exact command and before/after](evidence/charlotte-autopause-20261112/request-metadata-validation.json),6PASS after3PASS/1FAIL/2ERROR before.

Final browser observations contain41 completed journeys and zero uncaught JavaScript exceptions. Intentional simulated HTTP500/422 and aborted requests remain recorded; they were not suppressed. Raw incident and browser evidence stays local/ignored. Reproducible regression source is committed.

**Release status for this follow-up: NOT YET RELEASED. Full new QA CI is pending at report creation. No new main promotion, application deployment, actual telephony test, managed schema change or production call control was performed.**
