# Campaign enrollment timeout — 19 November 2026

## Confirmed incident

The user-visible reference `37c14f7886df` identifies request
`37c14f7886df48939c2f5884ec301b64`, 2026-11-19 00:21:22.651 UTC.
The authenticated campaign enrollment endpoint returned HTTP 500 after
15,044 ms. PostgreSQL cancelled the bulk enrollment statement, SQLSTATE 57014;
the stack reaches `app/campaigns/service.py:148` in live revision
`0674194aa629a02f2faf3591945a4524f18632e7`.

Read-only inspection confirmed the latest CSV import completed: 70,005 rows,
69,989 distinct contacts associated with valid rows and 16 invalid rows. The
newest campaign has zero memberships. The request payload is intentionally not
logged, so identifying this particular import/campaign pair as the failed
request's source/target is an inference, not direct request-body evidence.
The import and failed enrollment are separate transactions. No contacts were
removed by the failed enrollment.

The endpoint performs contact selection/locking, memberships and immutable
per-contact enrollment events in a single statement with a 15-second local
statement timeout. This is a confirmed size limitation of bulk enrollment.
Splitting the CSV is an operational workaround, not a shipped software fix or
proof that all larger batches fail. Recent live successful enrollment records
include a batch of 18,740; that does not establish a universal safe maximum.

## Isolation and evidence

The initial production investigation used `SET TRANSACTION READ ONLY`, metadata/log reads
and plan-only EXPLAIN (no ANALYZE). During that initial phase no live contacts, campaign memberships,
configuration, calling permissions or containers were modified. A later,
explicitly authorized recovery is documented below. No deployment, merge or
real call was initiated by either phase.

A new local Compose project, `ut-qa-enrollment-20261119`, uses PostgreSQL 18,
current migrations through `0012_incoming_runtime`, communications disabled,
DB host `db`, a verified `synthetic_only` sentinel, and synthetic contacts only.
It mounts current backend source read-only over the cached dependency image;
the image itself was not rebuilt and is not claimed to be a new release image.
The local database CPU limit is 0.5 CPU. Timings are evidence from this laboratory,
not production latency guarantees.

Every command below was executed via `python3 qa-reports/tools/run_check.py
<name> -- <command>`. Its paired JSON records the complete command, source
revision, times, exit code and output hash. Raw evidence is ignored by Git and
kept locally under `qa-reports/evidence/`.

| Check | Command after recorder prefix | Status / exit | Evidence |
|---|---|---|---|
| Exact error reference | SSH invocation recorded in `campaign-enrollment-reference.json` | PASS / 0 | `evidence/campaign-enrollment-reference.{json,log}` |
| Volume, activity and plan-only inspection | SSH invocation recorded in `campaign-enrollment-volume-final.json` | PASS / 0 | `evidence/campaign-enrollment-volume-final.{json,log}` |
| First diagnostic attempt | SSH invocation recorded in `campaign-enrollment-volume.json` | FAIL / 1: diagnostic used nonexistent `identity_audit.entity_id`; corrected to `subject_id` | `evidence/campaign-enrollment-volume.{json,log}` |
| Fresh laboratory database | `sudo -n docker compose -p ut-qa-enrollment-20261119 -f compose.yaml -f qa-reports/evidence/flexible-qualification-20261116/compose.qa.yaml up -d --no-build --pull never --wait db objectstore` | PASS / 0 | `evidence/enrollment-lab-start.{json,log}` |
| Current migrations | Same Compose arguments, `run --rm --no-deps migrate` | PASS / 0 | `evidence/enrollment-lab-migrate.{json,log}` |
| API and gateway startup | Same Compose arguments, `up -d --no-build --pull never --wait api gateway` | PASS / 0 | `evidence/enrollment-lab-api.{json,log}` |
| Unchanged 70,000-contact enrollment | `python3 qa-reports/evidence/campaign-enrollment-20261119/reproduce.py` | FAIL / 1, expected defect reproduction: SQLSTATE 57014 after 15.108 s | `evidence/enrollment-70k-baseline.{json,log}` |

The baseline reproduction uses the actual service and migrated tables, including
foreign keys, immutable history and runtime database role. It does not disable
constraints or assertions. Its timeout occurred during a membership foreign-key
check, confirming work was still executing; this is not evidence of a specific
missing index or of a persistent production lock.

## Workaround validation and remaining limitations

The separate `verify-batches.py` script checks that the failed 70,000 enrollment
rolled back every membership/event, then partitions the same synthetic contacts
into seven completed imports of 10,000 rows and calls the unchanged service.
It asserts exactly 10,000 additions per batch; retries the same request and
re-enrolls the same source to assert no duplicate membership/event additions;
finally checks all 70,000 memberships and 70,000 per-contact enrollment events.
Final results are appended below after execution.

No application code was changed. Bulk enrollment around 70,000 contacts remains
an unresolved defect in the current release. A durable, bounded background
enrollment workflow would address the general case; no speculative queue/schema
change or timeout increase was applied during this investigation.

NOT TESTED in this incident response: browser enrollment workflow, fresh CSV
upload/preview/application, real telephony, migration rollback, full application
regression or release security scan. These are not implied PASS by the focused
service checks. The user's current request permits splitting the CSV as the
immediate workaround.

### Final batch results — PASS / exit 0

Executed command: `python3 qa-reports/tools/run_check.py enrollment-seven-10k-batches -- python3 qa-reports/evidence/campaign-enrollment-20261119/verify-batches.py`.

All seven 10,000-contact batches passed. Per-batch enrollment seconds: 5.913, 5.529, 5.809, 5.794, 5.877, 5.579, 6.014. Atomic rollback, same-request replay, repeated-source deduplication, final membership count and immutable event count assertions passed. Evidence: `evidence/enrollment-seven-10k-batches.{json,log}`.

Operational recommendation: CSV files of at most 10,000 data rows each, preserving the header, imported and added to the same campaign one at a time. Re-imports deduplicate contacts by normalized phone in the existing import logic, but the CSV upload/import path itself was not re-executed in this incident check. A deployment is not required to use this workaround.

## Authorized recovery completed — 19 November 2026

After the operational workaround recommendation, the user explicitly asked
“can u do it”. Fresh read-only metadata confirmed that the same administrator
owns completed `CVC_MONTREAL_GHL.csv` and the active, empty `CVC MTL` campaign.
The original import was reused; no duplicate CSV objects or synthetic import
records were created on the live database.

A reviewed operator utility, `scripts/enroll_campaign_import_batches.py`, adds
at most 500 source rows per transaction, using the normal runtime database role.
It preserves the enrollment SQL's canonical contact lock order, active-card
stage/order/version, inactive-card reactivation, global restriction stages,
original import foreign key, immutable per-contact events and administrator
audit. Batch request IDs are deterministic, and progress is committed with the
membership/event transaction, so a retry resumes safely. Source owner/hash,
campaign identity/activity and administrator status are checked. Lock waits are
bounded to 750 ms with limited retry for explicit contention SQLSTATEs. It does
not raise the application's statement timeout or edit application files.

### Focused regression execution

`python3 qa-reports/tools/run_check.py enrollment-operator-regressions-runtime-path -- sudo -n docker compose -p ut-qa-enrollment-20261119 -f compose.yaml -f qa-reports/evidence/flexible-qualification-20261116/compose.qa.yaml run --rm --no-deps -e PYTHONPATH=/app -v /home/codexdev/unlimited-talk-qa-audit/scripts/enroll_campaign_import_batches.py:/enroll_batches.py:ro -v /home/codexdev/unlimited-talk-qa-audit/tests/verify_enrollment_operator.py:/verify.py:ro api python /verify.py`

PASS / exit 0, 7.303 seconds, real migrated PostgreSQL with the runtime role and
1,005 synthetic source rows: 1,000 distinct valid contacts, one repeated contact
across batch boundaries and four invalid rows. Five printed check groups cover:

- Default dry run, source cardinality and completed-source checks.
- Injected audit failure rolls back membership creation, inactive reactivation
  and all immutable events; no partial transaction is accepted.
- Simultaneous delivery of the same batch, deterministic replay, interrupted-run
  resume, duplicate-source contacts and invalid-row exclusion.
- Active stage/order/version preservation, inactive reactivation, global flags,
  exact source provenance, unchanged canonical contacts/imports/source rows,
  exactly-once per-contact events and administrator audit.
- Rejection of wrong owner/hash/name, non-admin actor, archived campaign and
  oversized batches.

Evidence: `evidence/enrollment-operator-regressions-runtime-path.{json,log}`.
Two earlier harness attempts failed and are retained: the `/operator.py` mount
shadowed Python's standard-library `operator` module; the renamed mount then
needed `PYTHONPATH=/app` when invoking an absolute test file. These failed before
fixture execution and were corrected without weakening any assertion. Evidence:
`enrollment-operator-regressions` and
`enrollment-operator-regressions-mount-fixed` JSON/log pairs.

### Live execution and independent verification

The protected root wrapper verifies the exact live revision, schema and original
enrollment service checksum, the reviewed utility checksum and API readiness
before running. A private root-owned JSON-lines ledger records every committed
batch; no contact names, phone numbers, profiles or credentials are logged.

All commands use the SSH identity, strict host verification and full command
recorded in their evidence JSON. The command following the shared SSH arguments
is shown here:

| Check | Remote command | Result | Evidence prefix |
|---|---|---|---|
| Fresh source/target/owner verification | `python3 /root/qa-enrollment-preflight-operator-20261119.py` | PASS / 0 | `campaign-enrollment-operator-preflight` |
| No-write dry run | `python3 /root/run-cvc-mtl-enrollment-20261119.py` | PASS / 0; 69,989 valid contacts, zero memberships | `campaign-enrollment-operator-dry-run` |
| Authorized bounded enrollment | `python3 /root/run-cvc-mtl-enrollment-20261119.py apply` | PASS / 0; 141 committed batches, 69,989 additions, 45.277 seconds including transport/checks | `campaign-enrollment-operator-apply` |
| Independent read-only SQL and service health verification | `python3 /root/verify-cvc-mtl-enrollment-20261119.py` | PASS / 0 | `campaign-enrollment-operator-verify-live` |

Final read-only SQL confirms:

- 69,989 distinct source contacts and 69,989 active memberships; zero missing.
- All 69,989 memberships reference the original import.
- Exactly 69,989 per-contact enrollment events for 69,989 distinct contacts.
- Original import remains completed: 70,005 processed rows, 16 invalid, original
  SHA256 unchanged.
- 69,987 cards are “À appeler”, one “Ne pas contacter”, one “Non intéressé”;
  zero mismatches with canonical global restrictions.
- API readiness HTTP 200; all seven services running, all six configured health
  checks healthy. Source revision remains
  `0674194aa629a02f2faf3591945a4524f18632e7`. No deployment/restart was performed.

This resolves this import's enrollment. It does not repair the general UI bulk
70,000-contact timeout, remove invalid rows, prove browser behavior, or constitute
a new production-release certification. No real call was initiated by the
operator. The user can refresh the existing campaign to see the imported cards.

Verified source SHA256 `scripts/enroll_campaign_import_batches.py`: `b055f48218d367fbdeb7a92081bde6e05fc45822a554cce5ad6e2c019c9b8b26`.

Verified source SHA256 `tests/verify_enrollment_operator.py`: `c2176bf8b7068627140eba8561eb005e954cc7a3ce13634a8f59ecb070a304e8`.

Verified source SHA256 `backend/app/campaigns/service.py`: `e2e2eaf205506eb318d68f7fd097a08d0f49baa7250edce88c9d65a7e3a2584c`.
