# Booking validation and draft retention — 14 November 2026

## Confirmed defects and scope

Live read-only diagnosis confirmed repeated HTTP422 responses on both appointment creation and qualification draft saving. Submitted bodies and validation details were intentionally absent from old logs, so the exact offending answer in the two agents’ submissions is **NOT DETERMINED**. Imported postal prefill in their latest inspected contacts was empty; no Unicode-space defect was found in their actual stored input. No production appointment/contact writes or real calls were made during this investigation.

1. **MEDIUM — booking rejection hides the affected field.** The global validation handler replaces all explanations with an array of generic errors; the current UI converts this to “Vérifiez les champs du formulaire.” This also hides invalid qualification values during draft saving. New allowlisted static French feedback identifies mandatory questions, invalid choices/text, postal format and schedule fields. Only known schema labels are exposed; raw inputs, unknown field names and exception messages remain redacted. Authentication error behavior is unchanged. Safe `X-Error-Code` values identify the rejected field in future structured request logs.
2. **MEDIUM — valid Canadian postal codes copied with Unicode spaces or a central dash are refused.** Reproduced on synthetic input, in both draft and complete booking validation. Presentation normalization now accepts whitespace, lowercase and a single central dash; saved format stays `H2X 1Y4`. Invalid letters/digits and other punctuation remain rejected. This is a confirmed independent defect, **not proof that it caused the agents’ particular incidents**.

No database migration, mandatory-field removal, authorization change, appointment write on the agents’ behalf or call-control modification. Existing schema1/2/3 snapshots retain their versions. Construction year remains optional text. Existing open browser forms already display string error details from the API; backend feedback needs no browser refresh to render, and refresh would discard unsaved answers.

## Executed checks

Evidence is local/ignored and retained with commands, UTC, actual exits, source/diff and output hashes. Baseline failures are preserved. Unit counts describe executed methods, not a coverage percentage. The browser checks run Chromium with mocked business API/phone boundaries; the separate HTTP/PostgreSQL suite exercises real server/database code in an isolated communications-disabled project. No claim of real carrier acceptance or reproduction of the agents’ exact input.

| Check | Status | Exit | Evidence |
|---|---|---|---|
| rdv-feedback-before | FAIL | 1 | [metadata](evidence/rdv-feedback-before.json), [log](evidence/rdv-feedback-before.log) |
| rdv-feedback-after | PASS | 0 | [metadata](evidence/rdv-feedback-after.json), [log](evidence/rdv-feedback-after.log) |
| rdv-backend-full | PASS | 0 | [metadata](evidence/rdv-backend-full.json), [log](evidence/rdv-backend-full.log) |
| rdv-frontend-build | PASS | 0 | [metadata](evidence/rdv-frontend-build.json), [log](evidence/rdv-frontend-build.log) |
| rdv-frontend-format | PASS | 0 | [metadata](evidence/rdv-frontend-format.json), [log](evidence/rdv-frontend-format.log) |
| rdv-lab-migrate | PASS | 0 | [metadata](evidence/rdv-lab-migrate.json), [log](evidence/rdv-lab-migrate.log) |
| rdv-http-postgresql | PASS | 0 | [metadata](evidence/rdv-http-postgresql.json), [log](evidence/rdv-http-postgresql.log) |
| rdv-browser-regression | PASS | 0 | [metadata](evidence/rdv-browser-regression.json), [log](evidence/rdv-browser-regression.log) |

- Baseline: seven test methods; four assertion failures and four subtest errors reproduce missing field feedback and rejected presentation variants. Existing invalid-postal/privacy assertions already passed.
- Fixed: seven focused unit methods PASS; complete backend suite **227 tests PASS**.
- Browser: **10 tests PASS**, zero uncaught browser exceptions, including targeted postal error, preserved date/city/answers, correction and successful retry; qualification conflict/reload, no-RDV next contact, saved-field behavior, old snapshots, optional construction year, appointment pipeline, responsive layout and accessibility covered by surrounding executed scenarios.
- Real HTTP/PostgreSQL: appointment and draft errors contain safe postal feedback; invalid requests leave qualification/pipeline unchanged; nonbreaking-space/lowercase postal books successfully and persists canonically; shared calendar permissions, DST, idempotency, overlapping meetings, concurrent edits, immutable history, optional year and pagination PASS. Fresh isolated PostgreSQL schema upgrades to0012 PASS. No schema change is introduced.
- Build/typecheck and formatting PASS. No live bookings were submitted; agent-specific acceptance remains NOT TESTED pending deployment and retry with their saved answers.

## Exact commands

### rdv-feedback-before: FAIL, exit 1

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -e PYTHONDONTWRITEBYTECODE=1 -v /home/codexdev/unlimited-talk-qa-audit/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro unlimited-talk-qa-audit:dependency-hardened python -m unittest discover -s /tests -p test_booking_validation_feedback.py -v
```

### rdv-feedback-after: PASS, exit 0

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -e PYTHONDONTWRITEBYTECODE=1 -v /home/codexdev/unlimited-talk-qa-audit/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro unlimited-talk-qa-audit:dependency-hardened python -m unittest discover -s /tests -p test_booking_validation_feedback.py -v
```

### rdv-backend-full: PASS, exit 0

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -e PYTHONDONTWRITEBYTECODE=1 -v /home/codexdev/unlimited-talk-qa-audit/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro -v /home/codexdev/unlimited-talk-qa-audit/scripts:/scripts:ro unlimited-talk-qa-audit:dependency-hardened python -m unittest discover -s /tests -p 'test_*.py' -v
```

### rdv-frontend-build: PASS, exit 0

```sh
npm --prefix frontend run build
```

### rdv-frontend-format: PASS, exit 0

```sh
npm --prefix frontend run format:check
```

### rdv-lab-migrate: PASS, exit 0

```sh
sudo -n docker compose --project-directory /home/codexdev/unlimited-talk-qa-audit -p ut-rdv-20261114 -f compose.yaml -f qa-reports/evidence/ikram-booking-20261114/compose.qa.yaml run --rm --no-deps migrate
```

### rdv-http-postgresql: PASS, exit 0

```sh
env 'FOUNDATION_COMPOSE_ARGS=-p ut-rdv-20261114 -f /home/codexdev/unlimited-talk-qa-audit/compose.yaml -f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/ikram-booking-20261114/compose.qa.yaml' FOUNDATION_TEST_URL=http://127.0.0.1:18314 python3 tests/verify_calendar.py
```

### rdv-browser-regression: PASS, exit 0

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=rdv-feedback npm --prefix frontend run test:browser -- autodialer.spec.ts --grep 'qualification :|fiche pendant l’appel : réservation'
```

## Release boundary

Local validation passes for this scoped patch. Main CI and image publication must succeed for the exact new commit before normal guarded deployment. This report does not override broader production-readiness blockers or certify real telephony, twenty-agent media or disaster recovery. Keep open forms/drafts intact; deployment must respect the active-call guard. Root cause of the two particular submissions remains unconfirmed until a corrected error response or exact input is available.
