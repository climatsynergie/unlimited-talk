# Shift reliability corrections — 27 November 2026

Status: local fixes implemented; full release validation/deployment pending. No production application restart, real-call origination or monitoring/email restart has been performed by this change.

## Evidence-based findings and fixes

1. HIGH: voicemail-disposition requests can deadlock with signed screening callbacks (PostgreSQL40P01, four observed HTTP500s). Deterministic regression establishes the actor/intent lock inversion. Screening now acquires the actor key-share before locking the intent, matching authenticated UI order. The same regression fails before and passes after; one disposition and correct durable hangup are asserted. Authentication locks were not weakened.
2. HIGH: API pool starvation under simultaneous agent requests (18 observed HTTP500s). Under an identical bounded workload of20 queries behind two slow holders, the old two-slot pool completes12 and times out8; the five-slot API pool completes20 with zero errors. Four serial background processes use one slot each; the independently deployed observer keeps two. Aggregate maximum11 stays within the managed runtime role's12 connections; no overflow or relaxed three-second runtime statement/checkout deadline.
3. HIGH: directory/history queries scan imported profiles before paging (seven observed statement cancellations, roughly297k actual contacts). Empty filters no longer generate wildcard predicates. Call IDs page before directory joins. Literal substring semantics, quoted/full names, filters, agent scope and cursor pagination are preserved. Additive chronological and expression GIN indexes use owner-provisioned pg_trgm; runtime remains without DDL rights. Real disposable PostgreSQL proof uses300001 contacts and36000 call rows, explicit role denial, index idempotency, literal percent/underscore/backslash and injection-shaped input.
4. MEDIUM operational gap:23 inbound abandonments were observed with no ready-agent registrations in the reviewed shift. This is not proof of broken carrier routing. The top bar now exposes explicit reception activation/pause and connection status on every page for assigned agents. The admin dashboard counts available agents using exactly the router's session, SDK, busy and wrap-up rules. No automatic microphone activation, acceptance or agent assignment.

## Verification scope

-330 backend unit tests,40 host tests and175 phone-controller tests executed successfully.
-8 focused real-Chromium tests pass with mocked API/SDK, including global reception activation, no implicit SDK/microphone startup, navigation, pause without dropping the conversation,390px viewport, accessibility and admin coverage changes. These are browser tests, not real-carrier/audio acceptance.
-Real HTTP/PostgreSQL gates for authentication/CSRF/roles, imports, recording thresholds/exports, appointment context, signed Voice callbacks, call budgets, webhook ingress, reporting, incoming routing/voicemail and dialer races pass. Database outage/reconnect test passes.
-Online indexes are installed twice in disposable PostgreSQL; runtime maintenance is denied, contact/call/event fingerprints and schema0012 are unchanged. Existing populated-schema image rollback gate will also run against these indexes in Foundation CI.
-No dependencies or base-image digests change in this repair. Prior native-library findings are not cleared by these application regressions. Real carrier/media, human-versus-machine accuracy, provider quota remaining and20 simultaneous real agents are not certified here.

## Failures retained, not concealed

The voicemail baseline is an intentional failing regression. Initial fixture construction exposed local statement/memory limits and missing contact bindings; those fixtures were corrected without relaxing runtime route deadlines or expected results. Bulk seeding uses only the existing migration-role budget; all route assertions use the unchanged runtime deadline. A browser run was interrupted after discovering an incomplete laboratory (missing object-store bucket/worker), one wrong new-test route and a Docker-network-change navigation error. Its25 passed/2 skipped/94 unexecuted results are not a full-suite PASS. The complete isolated stack was then provisioned and integration tests rerun. A foundation invocation before gateway readiness failed; the ready-stack retry passed. One rollback attempt used a stale pre-existing local tag (actual2fb0463 rather than required662b450); retain that failed attempt and retry using the verified662 image. None of these laboratory failures is presented as a production defect or silently suppressed.

During complete-stack setup, the first generated Compose config retained default explicit local volume/network names. Migration authentication failed before any SQL was executed. That extra DB container was stopped immediately and recreated on uniquely named resources. Production is on the remote server and was never involved.

## Controlled rollout requirements

-Exact current-main Foundation CI including new regressions and existing migration/rollback/browser/security gates must pass; publish and verify the immutable attested image.
-Respect the existing active-call/dialer guard. Never stop an agent's active call. Preserve calling mode, incoming routes and the separate observer's11-campaign/provider5000 policy.
-Owner provisions pg_trgm in extensions with usage-only grants. Migrator builds both indexes CONCURRENTLY with2s lock and120s maintenance statement limits. No application-row update or destructive migration; leave additive indexes in place during an application rollback. Do not automatically drop an invalid index; inspect first.
-Verify actual deployed revision, readiness, calling enabled, worker health, index validity, connection limits and unchanged scope. Monitoring/email services remain disabled at the owner's request.

## Executed checks

Each linked JSON alongside its log records exact argv, source context, UTC, exit code and log hash. Some local runs preceded the final source commit; exact-source CI is the release gate. Full-suite and deployment results will be appended after execution.

| Check | Status | Exit | Evidence |
|---|---|---:|---|
| shift-api-pool-twenty-callers-20261127 | PASS | 0 | [qa-reports/evidence/shift-api-pool-twenty-callers-20261127.log](evidence/shift-api-pool-twenty-callers-20261127.log) |
| shift-backend-units-20261127 | PASS | 0 | [qa-reports/evidence/shift-backend-units-20261127.log](evidence/shift-backend-units-20261127.log) |
| shift-directory-search-scale-20261127 | FAIL | 1 | [qa-reports/evidence/shift-directory-search-scale-20261127.log](evidence/shift-directory-search-scale-20261127.log) |
| shift-directory-search-scale-batched-20261127 | FAIL | 1 | [qa-reports/evidence/shift-directory-search-scale-batched-20261127.log](evidence/shift-directory-search-scale-batched-20261127.log) |
| shift-directory-search-scale-bound-contacts-20261127 | PASS | 0 | [qa-reports/evidence/shift-directory-search-scale-bound-contacts-20261127.log](evidence/shift-directory-search-scale-bound-contacts-20261127.log) |
| shift-directory-search-scale-corrected-fixture-20261127 | FAIL | 1 | [qa-reports/evidence/shift-directory-search-scale-corrected-fixture-20261127.log](evidence/shift-directory-search-scale-corrected-fixture-20261127.log) |
| shift-directory-search-scale-large-fixture-20261127 | FAIL | 1 | [qa-reports/evidence/shift-directory-search-scale-large-fixture-20261127.log](evidence/shift-directory-search-scale-large-fixture-20261127.log) |
| shift-focused-browser-reception-dashboard-20261127 | PASS | 0 | [qa-reports/evidence/shift-focused-browser-reception-dashboard-20261127.log](evidence/shift-focused-browser-reception-dashboard-20261127.log) |
| shift-foundation-ready-stack-20261127 | PASS | 0 | [qa-reports/evidence/shift-foundation-ready-stack-20261127.log](evidence/shift-foundation-ready-stack-20261127.log) |
| shift-frontend-build-20261127 | PASS | 0 | [qa-reports/evidence/shift-frontend-build-20261127.log](evidence/shift-frontend-build-20261127.log) |
| shift-frontend-build-final-20261127 | PASS | 0 | [qa-reports/evidence/shift-frontend-build-final-20261127.log](evidence/shift-frontend-build-final-20261127.log) |
| shift-frontend-format-20261127 | PASS | 0 | [qa-reports/evidence/shift-frontend-format-20261127.log](evidence/shift-frontend-format-20261127.log) |
| shift-frontend-format-final-20261127 | PASS | 0 | [qa-reports/evidence/shift-frontend-format-final-20261127.log](evidence/shift-frontend-format-final-20261127.log) |
| shift-frontend-phone-controller-20261127 | PASS | 0 | [qa-reports/evidence/shift-frontend-phone-controller-20261127.log](evidence/shift-frontend-phone-controller-20261127.log) |
| shift-frontend-reception-build-20261127 | PASS | 0 | [qa-reports/evidence/shift-frontend-reception-build-20261127.log](evidence/shift-frontend-reception-build-20261127.log) |
| shift-host-units-20261127 | PASS | 0 | [qa-reports/evidence/shift-host-units-20261127.log](evidence/shift-host-units-20261127.log) |
| shift-integration-call_appointment_context-20261127 | PASS | 0 | [qa-reports/evidence/shift-integration-call_appointment_context-20261127.log](evidence/shift-integration-call_appointment_context-20261127.log) |
| shift-integration-call_budgets-20261127 | PASS | 0 | [qa-reports/evidence/shift-integration-call_budgets-20261127.log](evidence/shift-integration-call_budgets-20261127.log) |
| shift-integration-conversation_agenda-20261127 | PASS | 0 | [qa-reports/evidence/shift-integration-conversation_agenda-20261127.log](evidence/shift-integration-conversation_agenda-20261127.log) |
| shift-integration-dialer-20261127 | PASS | 0 | [qa-reports/evidence/shift-integration-dialer-20261127.log](evidence/shift-integration-dialer-20261127.log) |
| shift-integration-foundation-20261127 | FAIL | 1 | [qa-reports/evidence/shift-integration-foundation-20261127.log](evidence/shift-integration-foundation-20261127.log) |
| shift-integration-identity-20261127 | PASS | 0 | [qa-reports/evidence/shift-integration-identity-20261127.log](evidence/shift-integration-identity-20261127.log) |
| shift-integration-imports-20261127 | PASS | 0 | [qa-reports/evidence/shift-integration-imports-20261127.log](evidence/shift-integration-imports-20261127.log) |
| shift-integration-incoming_runtime-20261127 | PASS | 0 | [qa-reports/evidence/shift-integration-incoming_runtime-20261127.log](evidence/shift-integration-incoming_runtime-20261127.log) |
| shift-integration-recovery-20261127 | PASS | 0 | [qa-reports/evidence/shift-integration-recovery-20261127.log](evidence/shift-integration-recovery-20261127.log) |
| shift-integration-reporting-20261127 | PASS | 0 | [qa-reports/evidence/shift-integration-reporting-20261127.log](evidence/shift-integration-reporting-20261127.log) |
| shift-integration-reporting_incoming-20261127 | PASS | 0 | [qa-reports/evidence/shift-integration-reporting_incoming-20261127.log](evidence/shift-integration-reporting_incoming-20261127.log) |
| shift-integration-voice-20261127 | PASS | 0 | [qa-reports/evidence/shift-integration-voice-20261127.log](evidence/shift-integration-voice-20261127.log) |
| shift-integration-webhook_ingress-20261127 | PASS | 0 | [qa-reports/evidence/shift-integration-webhook_ingress-20261127.log](evidence/shift-integration-webhook_ingress-20261127.log) |
| shift-online-index-maintenance-20261127 | PASS | 0 | [qa-reports/evidence/shift-online-index-maintenance-20261127.log](evidence/shift-online-index-maintenance-20261127.log) |
| shift-pool-negative-and-fixed-20261127 | PASS | 0 | [qa-reports/evidence/shift-pool-negative-and-fixed-20261127.log](evidence/shift-pool-negative-and-fixed-20261127.log) |
| shift-populated-indexed-schema-rollback-20261127 | FAIL | 1 | [qa-reports/evidence/shift-populated-indexed-schema-rollback-20261127.log](evidence/shift-populated-indexed-schema-rollback-20261127.log) |
| shift-real-browser-suite-20261127 | FAIL | -2 | [qa-reports/evidence/shift-real-browser-suite-20261127.log](evidence/shift-real-browser-suite-20261127.log) |
| shift-real-incoming-http-pg-20261127 | FAIL | 1 | [qa-reports/evidence/shift-real-incoming-http-pg-20261127.log](evidence/shift-real-incoming-http-pg-20261127.log) |
| shift-reception-admission-reporting-20261127 | FAIL | 1 | [qa-reports/evidence/shift-reception-admission-reporting-20261127.log](evidence/shift-reception-admission-reporting-20261127.log) |
| shift-reception-admission-reporting-corrected-fixture-20261127 | PASS | 0 | [qa-reports/evidence/shift-reception-admission-reporting-corrected-fixture-20261127.log](evidence/shift-reception-admission-reporting-corrected-fixture-20261127.log) |
| shift-search-final-analyze-20261127 | FAIL | 1 | [qa-reports/evidence/shift-search-final-analyze-20261127.log](evidence/shift-search-final-analyze-20261127.log) |
| shift-search-fixture-and-runtime-final-20261127 | PASS | 0 | [qa-reports/evidence/shift-search-fixture-and-runtime-final-20261127.log](evidence/shift-search-fixture-and-runtime-final-20261127.log) |
| shift-search-role-guard-final-20261127 | PASS | 0 | [qa-reports/evidence/shift-search-role-guard-final-20261127.log](evidence/shift-search-role-guard-final-20261127.log) |
| shift-voicemail-concurrency-after-fix-20261127 | PASS | 0 | [qa-reports/evidence/shift-voicemail-concurrency-after-fix-20261127.log](evidence/shift-voicemail-concurrency-after-fix-20261127.log) |
| shift-voicemail-concurrency-before-fix-20261127 | FAIL | 1 | [qa-reports/evidence/shift-voicemail-concurrency-before-fix-20261127.log](evidence/shift-voicemail-concurrency-before-fix-20261127.log) |
| shift-voicemail-final-concurrency-20261127 | PASS | 0 | [qa-reports/evidence/shift-voicemail-final-concurrency-20261127.log](evidence/shift-voicemail-final-concurrency-20261127.log) |

## Validation update — 00:38 UTC

-Actual predecessor662b450 was verified by immutable image labels. Populated schema0012 plus both new indexes survives application rollback and restore: all37 table fingerprints unchanged, exit0. See `evidence/shift-indexed-schema-verified-predecessor-rollback-20261127.{json,log}`.
-Managed owner prerequisites executed successfully, no application DML: pg_trgm in extensions, usage-only grants, runtime still without staging CREATE and connection limit12. The application and indexes have not yet been rolled out. See `evidence/shift-managed-search-prerequisites-20261127.{json,log}` and the credential-free root operator source beside it. Credentials travelled through stdin only.
-The first candidate worker CI failed because its pinned base retained make_engine without the new optional pool_size argument while CI mounted the new shared-factory tests. This mismatch is independently reproduced as TypeError (negative control). The worker Dockerfile now copies the shared factory as well, preserving its existing default pool2. Building that exact pinned-base candidate and running all330 backend tests without a backend-source override passes, exit0. No test skipped or assertion weakened; current deployed worker276 is unchanged. Evidence: `shift-worker-pinned-db-api-before-fix-20261127`, `shift-worker-candidate-build-20261127`, `shift-worker-image-backend-tests-20261127`.
-Import publication concurrency/recovery regression passes all6 tests. Initial Foundation source e459 is superseded by the worker packaging correction; final current-main CI/publication must finish before deployment. Full-browser run on the complete isolated stack remains in progress.

## Reception failure-state regression — 00:53 UTC

The full128 browser scenarios (125 normal plus3 specialized browser/API/PG journeys) passed on the preceding candidate. An additional initial-session HTTP503 injection then reproduced a new global-indicator defect: assigned agents lost the control/error entirely when the first snapshot failed. Keep the assigned-user hint visible and its explicit activation usable; the server continues enforcing every registration/admission permission. The same injected-failure browser case now passes, followed by13 surrounding dashboard/session cases (14 total), including renewal, connection loss, password rotation, navigation and no implicit microphone activation. No tests or safety assertions were removed. Evidence: `shift-global-reception-load-failure-before-fix-20261127` (FAIL), `shift-reception-recovery-web-build-20261127` (PASS), `shift-global-reception-load-recovery-after-fix-20261127` (PASS). This final UI-only correction supersedes the preceding application CI candidate; full current-main CI must complete again before deployment.

Additional actual-production-predecessor35 image was pulled by digest and its source labels verified. The unchanged37-table rollback assertions also pass against that exact image on the populated synthetic indexed database, then restore the new application. Evidence: `shift-production-predecessor-image-20261127` and `shift-actual-production-predecessor-rollback-20261127`. No live application rollback was performed.

## Backup restore defect caught before rollout — 01:16 UTC

Foundation CI557 completed its backend, database, general browser and actual browser/API/PG call journeys, then FAILED the logical backup restore gate. The newly indexed staging-only archive omitted its pg_trgm dependency; the source application and new indexes were not deployed. The exact failure reproduces on the isolated populated database (`shift-indexed-contact-backup-restore-before-fix-20261127`, exit1, schema extensions absent).

Both the actual private snapshot producer and the restore test now select staging plus extensions and explicitly include pg_trgm. Selecting its schema alone was experimentally insufficient; explicit extension selection is required. The archive table of contents must contain both schema and extension. Restoration into a fresh disposable database retains every original business fingerprint assertion and additionally verifies the extension namespace plus both valid/ready indexes. The corrected restore test passes, exit0 (`shift-indexed-contact-backup-restore-after-fix-20261127`). The actual managed read-only schema-only snapshot producer also passes with verified TLS/migration role:138468 bytes, no table-data sections, archive list and full payload decode succeed, database_writes=false, full_restore_executed=false (`shift-managed-schema-snapshot-extension-20261127`). No production database restore or business-row write was performed.

This is a real logical-backup compatibility repair, not removal or weakening of a failed test. It supersedes557 and requires a new current-main CI/publication before deployment. Previously prepared release-specific operators/dispatchers must be rebound to the final source revision; do not use their old target SHA.

## Import-test execution failure isolated — 01:46 UTC

Foundation CIb526 was stopped at the pre-existing import-dispatch race gate. Direct log download required authenticated retrieval; a dedicated read-only diagnostic workflow followed the signed log redirect without forwarding credentials and exposed only sanitized synthetic failure text. The original failure was the extra Python process launched by docker compose exec inside the running dispatcher exiting137 (SIGKILL), not a failed business assertion (`shift-ci-b526-sanitized-failure-evidence.json`, retrieval run45924099348).

All20 local six-case repetitions pass (120 tests), as do a separate GitHub fresh canonical migration/identity/import prefix plus10 repetitions (60 tests, run45923419317). Three192MiB cold-start attempts did not reproduce an OOM; retain that explicitly failed hypothesis proof rather than claiming a confirmed kernel OOM cause. Original CI OOM counters were not retained. The measured local shared-container peak was187969536 bytes against201326592 bytes, with import-time64MiB Argon2 work per Python process.

The harness now runs the unchanged proof in its own short-lived dispatcher-service container, retaining the exact image, private local database/broker credentials, per-container CPU/memory limits,180s timeout and all six assertions. The actual background dispatcher remains running concurrently. This removes unnecessary resource contention between a test interpreter and the live daemon; no production application, import logic, authentication cost or resource cap changes. The focused isolated proof passes all6 tests (`shift-import-proof-own-container-20261127`, exit0). Full current-main CI remains the final gate. No failed assertion or test was removed or weakened.
