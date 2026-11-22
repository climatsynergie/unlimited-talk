# Recording duration filter and daily agenda TXT — 22 November 2026

## Behavior and boundaries

Conversations adds optional recording-duration filters strictly greater than 20,
30 or 60 seconds. The API filters parents before keyset pagination and returns
only recordings matching the selected threshold. Call duration/ringing time is
not substituted, multiple recordings do not duplicate calls, default behavior
and agent ownership remain unchanged. Duration is a sorting aid, not a voicemail
or human-speech classifier.

Agenda adds a TXT download for each day of the displayed week. Each file includes
all matching appointments starting on that local day (not just loaded list pages),
with the selected creator/phase/cancellation filters and calendar timezone.
Each appointment contains date/time and UTC offset, status, client name/phone,
address, every supplied qualification answer including construction year and
Hydro, notes, booking agent and campaign. No ownership duration, spouse presence
or equipment answer is inferred. The appointment's saved qualification snapshot
is used, not a newer unfinished contact draft. Legacy appointments fall back to
contact coordinates and explicitly report absent qualification. UTF-8 BOM keeps
French accents compatible with Windows editors.

No dependencies, migration, call state transitions, dialer policy, audio handling,
existing contact data or existing appointment records are changed. Shared calendar
export permissions match the existing shared calendar/detail permissions.

The authenticated attachment is `text/plain`, `no-store` and `nosniff`, with a
safe date-only filename and an audit record. Revocation is checked again before
returning private data. One export at a time per API process; the SQL snapshot
checks a 1,000-appointment/8 MiB budget before returning JSON. Excess size rejects
with a French error, not a silently incomplete file. File generation does not
hold the database connection. Browser downloads abort on unmount/filter change,
prevent duplicate clicks, validate MIME type and revoke temporary Blob URLs.

## Executed local validation

All rows below have paired JSON/log evidence in `qa-reports/evidence/`. JSON
contains the exact complete command, exit code, timing, revision and output hash.
Commands use `python3 qa-reports/tools/run_check.py <check> -- <command>`.

| Check / evidence prefix | Executed command after recorder prefix | Result |
|---|---|---|
| `conversation-agenda-unit` | Recorded hardened `docker run` with current app/tests/scripts mounted read-only; `python -m unittest discover -s /tests -p 'test_*.py' -v` | PASS / 0, 246 unit tests including 7 new text/date/size regressions |
| `conversation-agenda-build-final` | `npm --prefix frontend run build` | PASS / 0, TypeScript and Vite |
| `conversation-agenda-format` | `npm --prefix frontend run format:check` | PASS / 0 |
| `conversation-agenda-lab-start`, `-lab-migrate`, `-lab-api` | Recorded Compose project `ut-qa-conversation-agenda-20261122`, local `db`, disabled communications; start DB/object store, migrate, start API/gateway | PASS / 0 each; migrations through `0012_incoming_runtime` |
| `conversation-agenda-api-complete` | Recorded isolated Compose environment, `python3 tests/verify_conversation_agenda.py` | PASS / 0, 10 real HTTP/PostgreSQL tests |
| `conversation-agenda-calendar-regressions` | Same isolated environment, `python3 tests/verify_calendar_inbound.py` | PASS / 0, 24 tests |
| `conversation-agenda-reconfirmation-regressions` | Same isolated environment, `python3 tests/verify_backend_reconfirmation.py` | PASS / 0, 14 tests; overlaps inherited cases above |
| `conversation-agenda-browser-semantic-selectors` | `env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=conversation-agenda-semantic-20261122 npm --prefix frontend run test:browser -- call-history.spec.ts team-calendar.spec.ts calendar-reconfirmation.spec.ts` | PASS / 0, 20 Chromium tests, mocked business endpoints, keyboard/mobile/accessibility and download/error recovery checks |
| `conversation-agenda-real-browser-absolute-paths` | Recorded absolute Compose paths, local URL and cached image label; `python3 tests/verify_browser.py identity.spec.ts --grep 'conversations et agenda'` | PASS / 0, 1 Chromium → real HTTPS/API → migrated PostgreSQL journey; thresholds and downloaded TXT contents, desktop/mobile and Axe |

API tests exercise exact 20/30-second boundaries, absence of recordings, long
call/short recording distinction, multiple recordings, pagination after filtering,
agent/admin authorization, invalid thresholds, complete exports beyond 100 rows,
creator/phase filters, midnight boundaries, missing/latest saved qualifications,
revoked/anonymous users, invalid day/zone/UUID, 1,001-row rejection, 10 MB saved
qualification rejection and slot release after failure. Unit checks include
23/25-hour DST days, repeated-hour offset labeling, legacy profiles, all fields,
free-form postal codes, UTF-8 accents and refusal to emit a partial oversized file.

Local testing uses cached `unlimited-talk-qa-audit:dependency-hardened` with current
source/dist overlays, not a falsely labeled new release image. The browser harness
needs `GITHUB_SHA=qa-audit-fixed-96f5055` only to match that cached image's readiness
label; source tested is the mounted implementation. Full CI will build the exact
candidate image separately. Screenshots inspected:
`evidence/screenshots/agenda-txt-desktop.png` and `agenda-txt-mobile.png`.

## Preserved failed attempts

No failing assertion was removed or weakened. All attempt logs remain:

- `conversation-agenda-api`: 6 export checks passed, 3 recording fixtures failed
  the existing constraint requiring consumed_at for provider-assigned calls;
  synthetic fixtures were corrected to satisfy it.
- `conversation-agenda-api-with-byte-budget`: oversized fixture SQL had one extra
  parenthesis; corrected before the 10-test passing run.
- `conversation-agenda-browser`: 19 passed, 1 failed because Playwright's exact
  label selector includes the nested select options; tests now target the same
  combobox by accessible role/name. All 20 then passed.
- `conversation-agenda-real-browser`: fixture startup failed because Compose file
  paths were relative to the frontend working directory; rerun uses absolute
  paths. New synthetic call fixtures also enroll their contacts via the normal
  service before satisfying the existing campaign membership FK. No constraint
  or application assertion was bypassed.

## Read-only live observations before release

`conversation-agenda-live-readonly-preflight`: PASS / 0. Exact command is the SSH
invocation in its evidence JSON of
`python3 /root/conversation-agenda-preflight-20261122.py`. Live source was
`0674194aa629a02f2faf3591945a4524f18632e7`, schema 12, manual calling enabled and
API ready; observed zero active outgoing/incoming calls. Volumes: 15,248 calls,
9,799 recordings, 24 appointments. This is a snapshot, not deployment admission.

`conversation-agenda-live-read-performance`: PASS / 0. SSH invoked
`python3 /root/conversation-agenda-read-performance-20261122.py`. Read-only SQL
probes (joins and recording threshold selection, not a complete HTTP/20-agent
load test) returned 21 rows at each threshold: default 0.0216 s, >20 s 0.0726 s,
>30 s 0.0127 s, >60 s 0.0169 s. No production data was modified by these probes.

## Release state and residual risks

At preparation: candidate CI/publication/deployment pending; not reported PASS.
Deployment must retain the current source/provenance/active-call guards. Schema
remains 12 with no migration or history rewrite. The existing single-API
container replacement can create a brief HTTP interruption (previous incident
recorded separately); this feature does not claim zero-downtime deployment.

NOT TESTED here: real PSTN/audio acceptance, real-agent concurrency/load,
Safari/Firefox, and a new native-library vulnerability audit. No real call was
initiated. These features do not certify the entire application production-ready,
repair the separate large-enrollment timeout, or guarantee voicemail detection.
