# VM Hunter Nano corrections — prepared, not deployed

Date: 28 November 2026. Isolated branch: `fix/vmhunter-nano-reliability-20261128`, based on `3e01fd94606c43a3eb982382ac6ff282a6e13144`. This includes the previously prepared dialer-ownership correction as an ancestor. No merge into main, production write, deployment, service restart, real call, email or monitoring restart was performed.

## Corrected behavior

- Explicit Nano configuration (`VMHUNTER_QUOTA_SOURCE=provider`, `VMHUNTER_MONTHLY_ALLOWANCE=100000`) now starts successfully and reports the correct allowance. Monthly entitlement/renewal remains provider-owned; the prior 5,000 metadata field was not an enforced monthly cap. Free/legacy opt-in behavior remains supported, and unknown allowances still fail closed.
- Nano permits **20 concurrent analyses**, inside the provider's published 50 channels. A rolling **5-starts-per-second** limit applies before database admission, in the account-scoped durable admission transaction, and immediately before provider config frames. Burst rejection does not queue an agent or drop the ordinary call. The existing HTTP/decision contract stays unchanged.
- Pending asynchronous admissions reserve local capacity before yielding to the database. Failed admissions release that local reservation. Local rate saturation does not impose the provider-failure global backoff.
- Recovery and admission use one set-based cleanup lookup. It first subtracts confirmed results from claim IDs, then checks the remaining exact nonce/call/state proofs. This avoids broad journal primary-key scans and repeated nested anti-join work. Runtime query timeout remains 1.5 seconds; no assertion or timeout was weakened to make it pass.
- Two optional additive indexes support recent claims and confirmed stream stops. Installation remains explicit, concurrent and migration-role-only; it is repeatable and performs no business-row mutation. Schema head remains `0012_incoming_runtime`; no schema migration or new runtime DDL rights are required.
- Cleanup warnings now include a sanitized SQLSTATE without SQL, parameters, audio or credentials. The prior live OperationalErrors lacked this information, so their exact individual causes cannot all be retrospectively established. A matching query-timeout failure was reproduced and fixed in disposable PostgreSQL.
- The future worker rollout operator accepts Nano explicitly, reserves **512 MiB / 1 CPU** for the dedicated media worker, preserves its two-connection DB pool and all existing isolation/secrets, and checks allowance and effective capacity after rollout. Known compatible API revisions include the current reliability API and pending ownership API; unknown/unhealthy APIs still fail validation. Ordinary deployment guards were not changed.

## Executed evidence

Working directory: `/home/codexdev/unlimited-talk-vmhunter-nano`. Each check below has `qa-reports/evidence/<check>.json` with its exact argv, timestamp, exit code, source context and log hash, plus `<check>.log`. Evidence is retained locally; it contains synthetic data or sanitized production metadata only.

The recorder invocation is `python3 qa-reports/tools/run_check.py <check> -- <command>`. No test below uses production data writes or originates PSTN calls.

| Check | Result | Exit | Evidence / executed behavior |
| --- | --- | --- | --- |
| `nano-db-readonly-before-20261128` | PASS: inspection, not incident resolution | 0 | `python3 qa-reports/evidence/nano-db-diagnostics-readonly.py`: installed lookup index valid; live old plan walks `voice_events_pkey`, estimated full-path cost approximately 1.1 million; three bounded old cleanup lookups complete in 0.628–0.718 s. Individual prior OperationalError causes remain unknown. |
| `nano-before-regressions-20261128` | FAIL: expected pre-fix reproduction | 1 | Isolated `python -m unittest -v test_vmhunter_nano`: seven tests, two assertion failures and four errors. Third analysis bypassed; overlapping admission awaits could exceed local reservation count in a fake store; Nano metadata/rate support absent. The production DB's separate old two-slot guard was not bypassed by this fake-store proof. |
| `nano-build-worker-20261128` | PASS | 0 | `sudo -n docker build --build-arg GIT_REVISION=qa-nano-20261128 -f deployment/vmhunter/Dockerfile -t unlimited-talk-vmhunter-nano:qa .` |
| `nano-image-source-20261128` | PASS | 0 | `python3 qa-reports/evidence/nano-image-source-check.py`: SHA-256 comparison confirms the image's database factory, VM client and observer exactly match this worktree. Local tested image ID: `sha256:db4fc66587045b28f811536f0751ceea33b740ea50cbe7e9f10178015db1bae9`. This QA-labelled image is not an attested production artifact. |
| `nano-worker-image-backend-final-20261128` | PASS | 0 | Built worker, no backend source mount, network disabled, read-only filesystem, 512 MiB / 1 CPU: **342 tests passed**. Includes real loopback HTTP and WebSockets with twenty simultaneously bound media sockets, unique call/stream bindings, five config starts per rolling second, all twenty results and confirmed cleanup, and no active job left over. This uses synthetic provider verdicts, not real audio accuracy. |
| `nano-current-backend-final-20261128` | PASS | 0 | Full current API source mounted over the dependency image, network disabled, 256 MiB / 1 CPU: **342 tests passed**. Confirms compatibility with the complete pending application source, not only the independent worker image. |
| `nano-host-final-20261128` | PASS | 0 | `python3 -m unittest discover -s tests/host -p 'test_*.py' -v`: **41 tests passed**, including explicit Nano configuration, preserved secrets/isolation, exact known API compatibility and refusal of unsupported configurations. |
| `nano-built-screening-postgres-20261128` | PASS | 0 | Fresh schema12 + built image: `python3 tests/verify_vmhunter_screen.py vmhunter-screen-integration.py`. Signed pre-bridge HTTP, 19 safe decision cases, 24 synthetic analyses, two-agent continuation, unchanged manual/unselected scope, missed start/deadline/database-outage recovery, explicit pause/stop preserved; zero real calls. |
| `nano-built-capacity-concurrent-completions-20261128` | PASS | 0 | Fresh schema12 + built image: `python3 tests/verify_vmhunter_screen.py vmhunter-nano-integration.py`. Starts with 5,006 prior-period claims; uses all twenty slots; rejects sixth start within a second and twenty-first active analysis; restart preserves account limits; result frees a slot; twenty concurrent completions share only two database connections; runtime DDL denied; index install repeatable with unchanged data fingerprints; optional index rollback preserves data and prior Free configuration. |
| `nano-built-cleanup-postgres-20261128` | PASS | 0 | Fresh schema12 + built image: `python3 tests/verify_vmhunter_screen.py vmhunter-cleanup-recovery-integration.py`. Live calls cannot clear cleanup; exact account/call/pilot/nonce required; competing supervisors append idempotently; late terminal recovery; recent interrupted claims remain visible; journal facts preserved; INITIALSILENCE continues. |
| `nano-built-scale-postgres-20261128` | PASS, with expected failed legacy comparator | 0 | Fresh schema12 + built image: `python3 tests/verify_vmhunter_screen.py vmhunter-cleanup-scale-integration.py`. 120,000 unrelated journal entries and 5,006 prior-period claims. Exact old query times out (`57014`) at 1.5 s; corrected query completes in **19.664 ms**, using the VM indexes without a broad events primary-key scan. Query-result semantics, journal fingerprint and schema retained. This is a local synthetic measurement, not a production latency guarantee or a 100,000-claim/month load certification. |
| `nano-original-provider-quota-clean-db-20261128` | PASS | 0 | Fresh disposable rerun of `vmhunter-provider-quota-integration.py` resolves the previous audit's non-fresh-fixture execution gap. More than 5,000 older claims impose no lifetime ceiling; previous fixed canary/scope/capacity/cleanup checks retained. |

The built-image PostgreSQL checks use `FOUNDATION_COMPOSE_ARGS='-f compose.yaml -f qa-reports/evidence/nano-built-image.json'`, where the override selects `unlimited-talk-vmhunter-nano:qa`. They do not set `VMHUNTER_USE_LOCAL_SOURCE`: application modules come from the actual built image. Each proof receives its own internal network and new tmpfs-backed database, migrates from empty to schema12, verifies synthetic-only metadata and disabled communications, then removes only its own containers/network.

Full backend commands, with worktree root substituted below only for readability (the evidence metadata retains exact absolute arguments):

```sh
sudo -n docker run --rm --network none --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL \
  --security-opt no-new-privileges --memory 512m --cpus 1 \
  -e PYTHONPATH=/app:/tests \
  -v "$PWD/tests:/tests:ro" -v "$PWD/scripts:/scripts:ro" \
  unlimited-talk-vmhunter-nano:qa \
  python -m unittest discover -s /tests -p 'test_*.py' -v
```

The current-API run uses `--memory 256m`, adds `-v "$PWD/backend/app:/app/app:ro"` and selects `unlimited-talk-shift:qa` as its dependency image.

## Retained intermediate failures

- `nano-capacity-postgres-20261128` and `nano-cleanup-scale-postgres-20261128`: **FAIL / exit 1**. The first candidate still allowed costly nested anti-joins during admission and cleanup; runtime statements hit the unchanged timeout. The final shared set-based query fixes both paths. No failing query test was removed.
- `nano-worker-image-backend-20261128`: **FAIL / exit 1**, 341 passing tests and one test-harness synchronization failure. The twenty synthetic result callbacks completed before their worker tasks had resumed and removed their job entries. The test now awaits both callbacks and task completion within the same bounded wait and still asserts all twenty results, all twenty stops and an empty job registry. Production logic was not weakened.
- Earlier focused/source-mounted successful runs remain evidence of development steps, not additional unique tests and not substitutes for the final built-image checks.
- `nano-format-before-20261128`: **FAIL / exit 2**, a trailing blank line in the new test file. Corrected without changing any test logic; the final commit passes the standalone whitespace check.

## Deferred release and rollback procedure — NOT EXECUTED

1. Include this branch with the pending ownership correction in the reviewed batch; refresh main and resolve any subsequent changes before publishing. Run exact-revision Foundation CI and VM Hunter Worker CI. This turn does not merge, dispatch deployment or publish an attested image.
2. Review/install the matching worker operator from this revision using the existing root-owned operator process. Keep the primary deployer, SSH restrictions and call-drain safeguards intact. Do not edit only the old worker's environment to `100000`: the old parser rejects it.
3. In the authorized release window, run the primary application deployment as usual after active calls finish and dialers pause. Install/verify the additive VM indexes with the migrator via `python /scripts/install_vmhunter_index.py --managed` in the reviewed migration container; leave runtime role permissions unchanged. This step was executed only on disposable local databases here.
4. Verify the independently attested worker's exact release SHA, then use the reviewed worker operator's `rollout RELEASE_SHA --provider-monthly-quota 100000`. It is a separate component; an ordinary API deployment does not automatically replace its image. Its post-check requires allowance100000, capacity20/CPS5, accepting=true and unchanged healthy API identity.
5. Check existing call flow, screening outcomes, latency, provider CPS/channel rejections and sanitized SQLSTATEs. Conduct controlled human/voicemail acceptance with an agent under explicit real-call authorization.
6. If rollback is needed, restore the recorded previous worker image **with its previous 5000 quota metadata/configuration**. An old parser cannot run with `100000`. This metadata rollback does not downgrade the paid provider subscription. Preserve call/journal data. The two new indexes can remain for compatibility; their optional concurrent removal was tested only locally. Existing rollout failure handling restores the previous compose/image and leaves filtering disabled until reviewed recovery, while ordinary calling stays available.

## Remaining boundaries

- **PASS:** corrections and applicable local automated checks above. No known failing case remains in these scoped local suites.
- **BLOCKED / deferred:** exact-main signed release publication, production operator/index/worker rollout and post-deployment observation, intentionally withheld until the user's later release window.
- **NOT TESTED:** real Nano maximum-load entitlement enforcement, actual human/voicemail detection accuracy and carrier audio quality, twenty human agents on their browsers/networks, new real telephony outage injections, every possible cause of the historical OperationalErrors. Synthetic test results do not establish those outcomes. No new browser UI was introduced or browser session exercised for this server-only patch.
- This remains one dedicated media worker. Account admission is durable; the final config gate is process-local. Horizontal multi-worker provider-start synchronization or other applications sharing the VM account was not certified.
- These fixes do not change reception, campaign membership, DNC, appointments/qualification, normal call duration, explicit dialer pause or existing disposition rules. Existing INITIALSILENCE/MAXWORD/CALLGUARD/failure continuations remain covered by executed regressions.

**Ready to include in the next reviewed release batch; not deployed and not a claim of global production readiness or perfect filtering.**

## Authorized release follow-up: CI fixture boundary

The owner authorized deployment on 28 November. Revision0724ac1 was fast-forwarded to main, but its worker CI run46093224096 failed at the first Nano burst assertion; the service was not deployed. A read-only diagnostic workflow retrieved only the test assertion location. A controlled disposable reproduction (`nano-ci-window-reproduction-20261128`, exit1) inserted and completed a preceding Free analysis immediately before the Nano burst, confirmed one recent account claim, and reproduced the same failure. The global five-starts-per-second limiter correctly counted that prior traffic.

The fixture now deliberately preserves that prior Free claim, waits for an empty rolling-second window and asserts the window is empty before testing the dedicated five-start burst. All capacity, elapsed-time, sixth-start, restart and concurrent-completion assertions remain. No runtime code or rate limit was relaxed. The corrected fixture is rerun against the built image in `nano-ci-window-corrected-20261128`. Exact-source GitHub checks and protected deployment must pass on the subsequent revision before activation.
