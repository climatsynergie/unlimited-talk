# Dialer ownership recovery — 27 November 2026

## Confirmed failure

An agent starts automatic calling, completes an attempt, reloads the same tab and explicitly starts again while the previous 90-second lease remains alive. `PhoneController` generates a new in-memory browser UUID; the old server guard rejects the new UUID even though authentication is unchanged. Real HTTP/PostgreSQL reproduces the exact 409 message, and a strict browser fixture reproduces the visible error. This is a confirmed cause, not proof that every reported incident has that cause.

The read-only live observation at 16:54 UTC found six dialer-control 409 responses involving two agents over eight hours. Request logs omit response details, so those six responses cannot all be classified as ownership conflicts. Six outgoing calls and eleven running dialers were active at that observation. No production state was modified by that inspection.

## Implemented repair

- An explicit Start/Resume action first reads a fresh server generation. A page load never arms or originates calls.
- A versioned request may reclaim a running lease from the same authenticated session, or from a deleted/expired/idle prior session belonging to the same agent. The backend recalculates eligibility under the existing user/dialer locks; the UI hint grants no permission.
- A second still-valid authentication session remains blocked while the lease is live. Missing or stale generations cannot recover it. Old-tab heartbeat/next/pause requests are fenced after recovery.
- Existing reserved, authorized, ringing and answered calls block recovery. A dead login never makes an active conversation disposable. Recovery never hangs up a call; provider-confirmed terminal state permits a later explicit retry.
- Concurrent recovery claims have one winner. CSRF, same-origin and campaign authorization remain enforced. Successful recovery emits a bounded `dialer.recovered` audit event; existing reporting counters remain unchanged.
- French UI shows “À reprendre sur cet onglet” and “Reprendre les appels ici” for recoverable state.

No schema migration, provider/media change, call-duration change, recording change, storage of credentials or background PSTN origination is introduced.

## Executed validation

- **FAIL before / PASS after:** actual HTTP/PostgreSQL reload recovery and old-tab fencing; strict Chromium reload/resume regression; controller reconstruction and cancelled-start regression.
- **PASS:** 177 phone/incoming/SDK controller tests; 330 backend unit tests; production frontend build and formatting checks.
- **PASS:** Complete dialer HTTP/PostgreSQL integration, plus generation fencing, foreign valid session, deleted/expired/idle previous sessions, preserved active calls, CSRF/origin/campaign denial and two simultaneous recovery claims. A strengthened variant uses actual automatic reservations and caller binding for all four active states.
- **IN PROGRESS:** complete HTTPS/browser/API/database rerun of the relevant browser files and exact-source remote CI.

## Retained laboratory failures

The first backend-unit invocation omitted the `/scripts` bind mount and produced 16 import/setup errors (242 tests discovered); the canonical hardened invocation with the required mount passed all 330 tests. Assertions were not removed.

The first wider browser run used the Vite HTTP preview without the real API fixture environment: 53 passed, 8 failed because the identity/CSP journeys require the production gateway, HTTPS and database fixture bootstrap. These are not relabelled PASS. A fresh isolated full project with a unique database volume/network is prepared for their rerun.

The first strengthened automatic-call fixture sent the principal caller number instead of the campaign-selected caller in a signed status callback; the application correctly rejected that mismatch with 403. Correcting the fixture to use the intent's actual caller preserves the production validation. All evidence remains retained.

## Deployment and limits

Production still runs `86230a2`; this new repair is NOT DEPLOYED. No calls have been initiated, ended or paused on production. No monitor/email service was restarted. Deployment must use the normal exact-main CI/provenance workflow and idle-call guard. Do not bypass active agents to release this fix.

Real-carrier audio and 17–20 human agents are NOT TESTED by this repair. The laboratory substitutes provider/SDK interactions. A successful automated recovery proof is not a whole-application production certification.

## Evidence register

Every record contains the executed command, source/diff context, UTC timestamps, actual exit code and hashed log. Before-fix failures and corrected fixture failures are intentionally preserved.

| Check | Status | Exit | Evidence |
|---|---|---:|---|
| ownership-backend-units-20261127 | FAIL | 1 | [ownership-backend-units-20261127.json](evidence/ownership-backend-units-20261127.json) · [log](evidence/ownership-backend-units-20261127.log) |
| ownership-backend-units-complete-fixture-20261127 | PASS | 0 | [ownership-backend-units-complete-fixture-20261127.json](evidence/ownership-backend-units-complete-fixture-20261127.json) · [log](evidence/ownership-backend-units-complete-fixture-20261127.log) |
| ownership-browser-after-fix-20261127 | PASS | 0 | [ownership-browser-after-fix-20261127.json](evidence/ownership-browser-after-fix-20261127.json) · [log](evidence/ownership-browser-after-fix-20261127.log) |
| ownership-browser-before-fix-20261127 | FAIL | 1 | [ownership-browser-before-fix-20261127.json](evidence/ownership-browser-before-fix-20261127.json) · [log](evidence/ownership-browser-before-fix-20261127.log) |
| ownership-browser-regressions-20261127 | FAIL | 1 | [ownership-browser-regressions-20261127.json](evidence/ownership-browser-regressions-20261127.json) · [log](evidence/ownership-browser-regressions-20261127.log) |
| ownership-complete-lab-start-20261127 | PASS | 0 | [ownership-complete-lab-start-20261127.json](evidence/ownership-complete-lab-start-20261127.json) · [log](evidence/ownership-complete-lab-start-20261127.log) |
| ownership-controller-after-fix-20261127 | PASS | 0 | [ownership-controller-after-fix-20261127.json](evidence/ownership-controller-after-fix-20261127.json) · [log](evidence/ownership-controller-after-fix-20261127.log) |
| ownership-controller-before-fix-20261127 | FAIL | 1 | [ownership-controller-before-fix-20261127.json](evidence/ownership-controller-before-fix-20261127.json) · [log](evidence/ownership-controller-before-fix-20261127.log) |
| ownership-frontend-build-20261127 | PASS | 0 | [ownership-frontend-build-20261127.json](evidence/ownership-frontend-build-20261127.json) · [log](evidence/ownership-frontend-build-20261127.log) |
| ownership-frontend-format-20261127 | PASS | 0 | [ownership-frontend-format-20261127.json](evidence/ownership-frontend-format-20261127.json) · [log](evidence/ownership-frontend-format-20261127.log) |
| ownership-http-pg-after-fix-20261127 | PASS | 0 | [ownership-http-pg-after-fix-20261127.json](evidence/ownership-http-pg-after-fix-20261127.json) · [log](evidence/ownership-http-pg-after-fix-20261127.log) |
| ownership-http-pg-automatic-call-safety-20261127 | FAIL | 1 | [ownership-http-pg-automatic-call-safety-20261127.json](evidence/ownership-http-pg-automatic-call-safety-20261127.json) · [log](evidence/ownership-http-pg-automatic-call-safety-20261127.log) |
| ownership-http-pg-automatic-caller-fixture-20261127 | PASS | 0 | [ownership-http-pg-automatic-caller-fixture-20261127.json](evidence/ownership-http-pg-automatic-caller-fixture-20261127.json) · [log](evidence/ownership-http-pg-automatic-caller-fixture-20261127.log) |
| ownership-http-pg-before-fix-20261127 | FAIL | 1 | [ownership-http-pg-before-fix-20261127.json](evidence/ownership-http-pg-before-fix-20261127.json) · [log](evidence/ownership-http-pg-before-fix-20261127.log) |
| ownership-http-pg-security-recovery-20261127 | PASS | 0 | [ownership-http-pg-security-recovery-20261127.json](evidence/ownership-http-pg-security-recovery-20261127.json) · [log](evidence/ownership-http-pg-security-recovery-20261127.log) |
| ownership-live-readonly-20261127 | PASS | 0 | [ownership-live-readonly-20261127.json](evidence/ownership-live-readonly-20261127.json) · [log](evidence/ownership-live-readonly-20261127.log) |
