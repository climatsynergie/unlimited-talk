# CVC QC enrollment — 19 November 2026

The user explicitly authorized enrolling the CVC Québec import, conditional on avoiding harmful application impact. Preflight found the matching completed CSV and active empty campaign with the same administrator owner, low host load, ample available host memory, healthy application services and no database lock waiters in the activity snapshot. The reviewed bounded enrollment utility was reused without application code changes.

Initial host load averages: 0.307 / 0.302 / 0.281 on 4 CPUs; available memory 6,791,240 kB of 8,131,772 kB. The current database used 784,029,375 bytes. These are point-in-time observations, not capacity or latency guarantees.

## Executed evidence

Each command below was executed using `python3 qa-reports/tools/run_check.py <check> -- <command>`. Paired evidence JSON includes the exact complete SSH command, revision, timing, exit status and log hash. SSH uses the existing dedicated identity, `BatchMode=yes`, `IdentitiesOnly=yes` and strict host-key verification.

| Check | Remote command after recorded SSH arguments | Result | Evidence prefix |
|---|---|---|---|
| campaign-enrollment-qc-preflight | `python3 /root/preflight-cvc-qc-enrollment-20261119.py` | PASS / exit 0; matching completed source, owner, empty campaign; resources and service health | `evidence/campaign-enrollment-qc-preflight.{json,log}` |
| campaign-enrollment-qc-dry-run | `python3 /root/run-cvc-qc-enrollment-20261119.py` | PASS / exit 0; 51,117 distinct valid source contacts; zero memberships; no writes | `evidence/campaign-enrollment-qc-dry-run.{json,log}` |
| campaign-enrollment-qc-apply | `python3 /root/run-cvc-qc-enrollment-20261119.py apply` | PASS / exit 0; 103 committed transactions of at most 500 source rows; 51,117 additions | `evidence/campaign-enrollment-qc-apply.{json,log}` |
| campaign-enrollment-qc-verify-live | `python3 /root/verify-cvc-qc-enrollment-20261119.py` | PASS / exit 0; independent read-only membership, event, provenance and health checks | `evidence/campaign-enrollment-qc-verify-live.{json,log}` |

Enrollment ran from 2026-11-19T13:33:59.851875+00:00 to 2026-11-19T13:34:38.705316+00:00 (38.853 seconds including transport and checks). The checksum-verified utility uses canonical contact locking, a 750 ms lock-wait limit, bounded contention retries, per-batch transactions, deterministic idempotency keys, original import provenance and immutable audit. Calling settings, application services and source imports were not changed; no deployment, restart or real call was initiated by the operator.

## Verified outcome

- 51,117 distinct source contacts, 51,117 active CVC QC memberships, zero missing; all currently in “À appeler”.
- Exactly 51,117 enrollment events for 51,117 distinct contacts, all with the original import provenance.
- Original import remains completed, 51,117 processed rows and zero invalid rows, with its checksum unchanged.
- No mismatches with canonical “Ne pas contacter” / “Non intéressé” restrictions.
- CVC MTL still has 69,989 memberships.
- API readiness HTTP 200; seven services running and all six configured health checks healthy. Application revision remains `0674194aa629a02f2faf3591945a4524f18632e7`.
- Final database size 808,744,639 bytes (24,715,264 bytes higher than preflight); final host load averages 0.527 / 0.361 / 0.299 on 4 CPUs. No harmful resource impact was observed in these snapshots.

API logs were inspected from the recorded enrollment start until verification. Zero structured request records were present in that window; no 5xx or slow-request entries were observed. The application omits fast successful requests from these logs, so this is not proof that a measured set of live agent journeys passed.

## Scope and limitations

The utility is byte-identical to the one regression-tested for the Montreal enrollment. Its SHA256 is `b055f48218d367fbdeb7a92081bde6e05fc45822a554cce5ad6e2c019c9b8b26`. Previous executed PostgreSQL regression evidence remains `evidence/enrollment-operator-regressions-runtime-path.{json,log}` (PASS / exit 0): atomic rollback, concurrent same-batch execution, restart/replay, duplicates, invalid rows, permission/state checks, source provenance and preservation of existing card state. Those regressions were not rerun because neither utility nor live enrollment service changed. The wrapper verified exact live service, schema, image revision and utility checksums before executing.

NOT TESTED in this operation: real browser campaign navigation, fresh CSV upload/application, real calls, concurrent real-agent acceptance or a full release regression/security scan. The general single-request large-import enrollment timeout is still unresolved; this operation safely completes this particular import and is not a production-release certification.
