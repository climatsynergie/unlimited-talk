# Calendar phases and incoming qualification — 17 November 2026

## Result

Implementation and focused validation complete; full CI/publication/deployment still pending at this checkpoint. No production appointment/contact was modified during QA and no real calls were initiated.

Calendar adds Confirmé (green), Vendu (blue), Annulé/Non Valide/Non Conforme (three readable red variants). The event, filter, accessible label, detail badge and dialog header share phase labels/colors. RDV booké, Terminé and Absent remain available. Business phases are retained in the existing immutable appointment-event snapshots, like qualification; their operational lifecycle maps to the existing four database states. Confirmé remains booked for callback/dialer exclusions; Vendu is completed; the three cancellation phases are cancelled. No migration or history rewrite is needed. Phase/lifecycle mismatches are rejected. Legacy edits preserve compatible phases; a preceding application can still read and edit the four operational states, while detailed phase display is unavailable there. Original event history remains immutable.

Incoming follow-up details now expose qualification, optional draft saving and booking. Only assigned active campaigns are offered to an agent; a single choice opens directly, multiple choices use a selector with bounded pagination. A known caller reuses the canonical contact; an unknown identified caller can be created and enrolled without duplication. CRM access, queue/campaign rights, opt-outs, ownership, optimistic versions and request replay checks remain enforced. Booking atomically saves the answers, moves the campaign card to RDV booké, cancels relevant campaign callbacks, and marks its source incoming follow-up handled with ownership/closure metadata.

Received-call history without a missed-call follow-up and the live incoming phone bar also expose qualification. These use the verified stored call/queue/caller context, not a browser-supplied phone or an invented missed-call interaction. Preparing/closing that form does not terminate incoming media. A draft is saved explicitly, and a real appointment still needs a date/time. All qualification fields remain optional and text/postal values remain unaltered. Call-backed bookings do not automatically merge other independent incoming follow-ups.

## Executed focused checks

-239 backend unit methods: PASS.
-24 real HTTP/PostgreSQL methods (14 existing reconfirmation/security regressions plus10 new phase/inbound cases): PASS. This includes replay, one-winner concurrent booking, unknown/known callers, spoofed contact, stale follow-up, queue/campaign authorization, opt-out, hidden caller, authentication and CSRF.
-Existing full calendar HTTP/PostgreSQL regression script: PASS, including permissions, transactions, pagination, DST and immutable history.
-38 real Chromium browser cases: PASS; plus4 existing visual/team calendar cases: PASS. Business API/media transports are isolated fixtures here; these are not live carrier/audio tests. Incoming live-media lifecycle counters are asserted unchanged while opening/closing qualification. The final booking payload's exact allowlisted keys prevent accidental UI context/schema metadata from leaking into the strict API body.
-Frontend production build and formatting: PASS.

## Failures retained and repaired

The first build caught using the phone hook wrapper rather than its stable controller; this was corrected. Initial API execution exposed unsupported inbound event action names and one randomly colliding test queue phone. Existing database action constraints were retained: the implementation uses valid followup.updated events with explicit reason/appointment metadata. Synthetic test numbers now choose an unused fixture value. The API suite then passed22,23 and finally24 methods as coverage expanded.

An initial browser run was aborted after a wrongly rooted Vite preview returned404; it is not an application pass. The corrected run found two test selectors expecting a heading where the accessible qualification control is a named fieldset/group. The next run found a missing booking-heartbeat fixture. Selectors/transport fixtures were corrected without suppressing error observations, network assertions, or data assertions. All intermediate FAIL/aborted artifacts are retained; final38+4 tests passed with no skipped cases.

## Review and remaining limits

The React review checks stable controller dependencies and cancellation on unmount, preserving drafts while requests/bookings are busy, keys bound to the current source, explicit hold/release only when taking an RDV, native fieldset semantics, visible text in addition to color, and scoped modal styles. Backend review checks bound SQL, authorization before mutation/replay, actor/campaign/request/contact/queue lock ordering, one canonical phone/contact, transactional source completion and immutable history.

No new real telephony acceptance was performed. Read-only provider queries at19:42UTC returned200 again for the number/account/alerts and the independent restricted key; that confirms restored REST authentication, not successful headset/PSTN calls. The prior billing incident is kept separate. Deployment must retain exact-source CI/provenance, idle-call and calling-restoration gates.

### calendar-inbound-unit — PASS, exit 0

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -e PYTHONDONTWRITEBYTECODE=1 -v /home/codexdev/unlimited-talk-qa-audit/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro -v /home/codexdev/unlimited-talk-qa-audit/scripts:/scripts:ro unlimited-talk-qa-audit:dependency-hardened python -m unittest discover -s /tests -p 'test_*.py' -v
```

[metadata](evidence/calendar-inbound-unit.json), [log](evidence/calendar-inbound-unit.log).

### calendar-inbound-http-postgres — FAIL, exit 1

```sh
env 'FOUNDATION_COMPOSE_ARGS=-p ut-qa-calendar-inbound-20261117 -f /home/codexdev/unlimited-talk-qa-audit/compose.yaml -f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/flexible-qualification-20261116/compose.qa.yaml' python3 tests/verify_calendar_inbound.py
```

[metadata](evidence/calendar-inbound-http-postgres.json), [log](evidence/calendar-inbound-http-postgres.log).

### calendar-inbound-api-security-final — PASS, exit 0

```sh
env 'FOUNDATION_COMPOSE_ARGS=-p ut-qa-calendar-inbound-20261117 -f /home/codexdev/unlimited-talk-qa-audit/compose.yaml -f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/flexible-qualification-20261116/compose.qa.yaml' python3 tests/verify_calendar_inbound.py
```

[metadata](evidence/calendar-inbound-api-security-final.json), [log](evidence/calendar-inbound-api-security-final.log).

### calendar-existing-api-regression — PASS, exit 0

```sh
env 'FOUNDATION_COMPOSE_ARGS=-p ut-qa-calendar-inbound-20261117 -f /home/codexdev/unlimited-talk-qa-audit/compose.yaml -f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/flexible-qualification-20261116/compose.qa.yaml' FOUNDATION_TEST_URL=http://127.0.0.1:18314 python3 tests/verify_calendar.py
```

[metadata](evidence/calendar-existing-api-regression.json), [log](evidence/calendar-existing-api-regression.log).

### calendar-inbound-browser — FAIL, exit 143

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=calendar-inbound npm --prefix frontend run test:browser -- calendar-reconfirmation.spec.ts inbound-callback.spec.ts
```

[metadata](evidence/calendar-inbound-browser.json), [log](evidence/calendar-inbound-browser.log).

### calendar-inbound-browser-correct-preview — FAIL, exit 1

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=calendar-inbound-correct-preview npm --prefix frontend run test:browser -- calendar-reconfirmation.spec.ts inbound-callback.spec.ts
```

[metadata](evidence/calendar-inbound-browser-correct-preview.json), [log](evidence/calendar-inbound-browser-correct-preview.log).

### calendar-inbound-browser-final — FAIL, exit 1

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=calendar-inbound-final npm --prefix frontend run test:browser -- calendar-reconfirmation.spec.ts inbound-callback.spec.ts incoming-session.spec.ts incoming.spec.ts
```

[metadata](evidence/calendar-inbound-browser-final.json), [log](evidence/calendar-inbound-browser-final.log).

### calendar-inbound-browser-release — PASS, exit 0

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=calendar-inbound-release npm --prefix frontend run test:browser -- calendar-reconfirmation.spec.ts inbound-callback.spec.ts incoming-session.spec.ts incoming.spec.ts
```

[metadata](evidence/calendar-inbound-browser-release.json), [log](evidence/calendar-inbound-browser-release.log).

### calendar-team-browser-regression — PASS, exit 0

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=calendar-team-regression npm --prefix frontend run test:browser -- team-calendar.spec.ts
```

[metadata](evidence/calendar-team-browser-regression.json), [log](evidence/calendar-team-browser-regression.log).

### calendar-inbound-build-complete — PASS, exit 0

```sh
npm --prefix frontend run build
```

[metadata](evidence/calendar-inbound-build-complete.json), [log](evidence/calendar-inbound-build-complete.log).

### calendar-inbound-format — PASS, exit 0

```sh
npm --prefix frontend run format:check
```

[metadata](evidence/calendar-inbound-format.json), [log](evidence/calendar-inbound-format.log).

### calendar-inbound-provider-readonly — PASS, exit 0

```sh
ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 /root/qa-cancelled-calls-20261117-provider-confirm.py
```

[metadata](evidence/calendar-inbound-provider-readonly.json), [log](evidence/calendar-inbound-provider-readonly.log).

## Full-suite follow-up: one unambiguous phase badge

QA CI44162188998 for dce6ee6 detected the existing full browser/API calendar cancellation test failing at identity.spec.ts:740. Publication was skipped. The new badge repeated the status already rendered in the metadata grid. A new focused regression reproduces the exact strict selector failure (Annulé resolves to two elements; exit1). The metadata duplicate was removed; the single colored badge remains. The existing identity workflow assertion was retained unchanged, and all five phase tests now assert a unique visible label in addition to phase persistence and computed header color. The focused11-case suite then passed.

### calendar-phase-duplicate-before — FAIL, exit 1

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=calendar-phase-duplicate-before npm --prefix frontend run test:browser -- calendar-reconfirmation.spec.ts --grep 'phase Annulé'
```

[metadata](evidence/calendar-phase-duplicate-before.json), [log](evidence/calendar-phase-duplicate-before.log).

### calendar-phase-single-badge-browser — PASS, exit 0

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=calendar-phase-single-badge npm --prefix frontend run test:browser -- calendar-reconfirmation.spec.ts
```

[metadata](evidence/calendar-phase-single-badge-browser.json), [log](evidence/calendar-phase-single-badge-browser.log).

### calendar-inbound-old-api-rollback — PASS, exit 0

```sh
env 'FOUNDATION_COMPOSE_ARGS=-p ut-qa-calendar-inbound-20261117 -f /home/codexdev/unlimited-talk-qa-audit/compose.yaml -f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/flexible-qualification-20261116/compose.qa.yaml' python3 qa-reports/evidence/calendar-inbound-rollback/run.py
```

[metadata](evidence/calendar-inbound-old-api-rollback.json), [log](evidence/calendar-inbound-old-api-rollback.log).

The rollback probe launches the exact preceding0e18ba6 API source in a second isolated container and reads every new phase through that old API over actual HTTP. It also edits through the old API, then verifies the expected operational fallback and unchanged historical phase snapshots through the new API. Schema0012 is unchanged. All synthetic project volumes were removed afterward; no managed database was used.
