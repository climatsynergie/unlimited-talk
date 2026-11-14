# Dialer server incident and durable query repair — 14 November 2026

The owner reported no sound and immediate pauses for Kawtar and Oumayma, then explicitly authorized direct server repair. This supersedes the initial read-only audit restriction for the targeted incident operations below. No real calls were initiated by the tools. Unrelated incoming UI work remains in the same QA branch and is preserved.

## QA-23 — HIGH: large queue selection times out before any call starts

Live source325e9e081bed2dabd7fe1a5e46657a52bff0ee8b was healthy, schema0012, with calling enabled. The new incoming UI source7976734 was **not deployed**. Logs show `/api/telephony/dialer/next` SQLSTATE57014, approximately3–3.8seconds, at `dialer_service.candidates`; affected attempts do not create a Voice reservation. Client diagnostics record `dialer.pause_cause.next_request.500`. This explains silence followed by pause for those attempts; it is not evidence of a PSTN audio-path failure.

The live planner scans canonical contacts/history before a large top-N sort. Estimates:106,177 contacts,148,135 memberships,152,018 campaign events,1,850 Voice intents. Selected campaigns contain39,367 and40,314 memberships. The older partial membership index starts with stage, which does not satisfy queue order across several callable stages. The early functional tests did not exercise this cardinality; repeated transient-request retries do not cure this persistent SQL failure.

## Authorized production recovery actually performed

1. Created `staging.campaign_contacts_dialer_queue(campaign_id,queue_position,contact_id) WHERE is_active` **CONCURRENTLY** using the migrator.2.909seconds; valid/ready. No customer/call rows modified. This alone did **not** cure the timeout; failure retained.
2. Read-only probes: disabling JIT alone still takes approximately2seconds. Selecting nested-loop plans with JIT disabled returns100 candidates in19–20ms for both affected campaigns.
3. At15:24:35–15:24:42UTC, committed defaults `jit=off`, `enable_hashjoin=off`, `enable_mergejoin=off` **only for ut_staging_runtime**. Prior values were unset; recorded before changing. Verified inherited settings on a fresh connection. Renewed five idle, same-role/same-host connections with no active transaction; no application restart or active transaction intentionally targeted. The small race between observing idle and terminating is a residual operational risk; any affected request can reconnect via the existing pool pre-ping.
4. Fresh inherited-settings executions: Kawtar9.272ms, Oumayma6.566ms,100 rows each. The owner confirmed recovery. Read-only observation through15:30:47UTC shows completed calls for Kawtar/Oumayma and other agents, with no new selection500 in the sampled post15:24:42 logs. This is a bounded observation, not a promise of permanent uptime.

**The role settings are emergency tuning and remain active.** They affect all queries by that application role, so reporting/import workloads need continued observation. They must be removed after the optimized code is deployed and checked, using the guarded reset procedure below. Calling admission, Twilio routing, account limits, call records and opt-out policy were not changed. The deployed application remains325e9e0 at this report's creation.

## Durable code change

Materialize at most100 **raw ordered membership/callback rows** before correlated eligibility/history checks. A lateral LIMIT keeps checks tied to each raw row. Preserve rejected rows solely to advance the raw keyset cursor; a completely rejected page cannot loop or hide later eligible contacts. Callback priority and every existing eligibility/quota/permission condition remain intact. Final reservation and provider-redemption checks/locks remain authoritative.

`next_call` disables JIT once with **SET LOCAL** only inside the selection transaction. It reverts when the transaction ends; other transactions retain their defaults. No query timeout was increased and no calling safeguard removed. The extra queue index is idempotently reproducible via `app.telephony.dialer_index`; historical migrations/data schema remain unchanged. CI verifies index role boundaries/idempotency and runs a new realistic-scale gate.

Realistic isolated PostgreSQL evidence includes106k contacts,148k memberships,152003 events and1850 intents. A matched original query fails the new generous1-second headroom assertion at1.692s; the candidate passes at0.347s and0.036s with transaction-local JIT disabled. Another cold original execution completed2.071s within the3s statement timeout: it is honestly preserved as PASS for that older threshold, not relabeled as a timeout. Fresh final candidate: first1000.188s;250 rejected plus two cooldown rows correctly skip to253 and prioritize due callbacks; all40000 ineligible rows exhaust in1.602s without looping. This is query scale/admission evidence, **not20 simultaneous real audio conversations**.

## Incoming CI fixture correction

The7976734 main and QA pipelines fail their final incoming-runtime gate; publication is skipped. Earlier browser scenarios may already create synthetic caller+16135550102. The added test wrongly assumed an absent/unrestricted caller, then attempted a duplicate insert. The corrected fixture reads the actual baseline, checks initial API flags against it, temporarily tests canonical flags/profile and restores the existing baseline. It does not weaken product validation or overwrite earlier scenario state. A local original-fixture failure with an existing restricted caller and the corrected complete incoming suite are retained. The exact remote failing traceback was unavailable; the GitHub gate failure and local reproducer are distinguished.

## Executed ledger

Recorder metadata links contain exact commands, exits, UTC intervals and hashes. An investigation command's PASS is not a telephony acceptance PASS. Raw evidence is ignored locally and was not pushed. No hidden test deletion or assertion weakening.

| Check | Status | Exit | Scope | Evidence |
|---|---|---|---|---|
| no-audio-live-readonly | PASS | 0 | Read-only incident investigation; SQLSTATE57014 /next failures, no new provider call for affected attempts | [metadata](evidence/no-audio-live-readonly.json), [log](evidence/no-audio-live-readonly.log) |
| no-audio-live-queue-index | PASS | 0 | Authorized production concurrent queue-index creation, valid/ready | [metadata](evidence/no-audio-live-queue-index.json), [log](evidence/no-audio-live-queue-index.log) |
| no-audio-candidate-after-index | FAIL | 1 | Index alone still exceeds3s: retained failure | [metadata](evidence/no-audio-candidate-after-index.json), [log](evidence/no-audio-candidate-after-index.log) |
| no-audio-candidate-jit-off | PASS | 0 | Read-only probe:2.04–2.07s; insufficient headroom | [metadata](evidence/no-audio-candidate-jit-off.json), [log](evidence/no-audio-candidate-jit-off.log) |
| no-audio-candidate-nested-probe | PASS | 0 | Read-only probe:19–20ms with three scoped planner options | [metadata](evidence/no-audio-candidate-nested-probe.json), [log](evidence/no-audio-candidate-nested-probe.log) |
| no-audio-live-planner-remediation | PASS | 0 | Authorized runtime-role defaults changed; five idle connections renewed, active transactions excluded | [metadata](evidence/no-audio-live-planner-remediation.json), [log](evidence/no-audio-live-planner-remediation.log) |
| no-audio-live-restored-selection | PASS | 0 | Inherited settings: Kawtar9.272ms / Oumayma6.566ms,100 candidate rows | [metadata](evidence/no-audio-live-restored-selection.json), [log](evidence/no-audio-live-restored-selection.log) |
| no-audio-live-recovery-observation | PASS | 0 | Read-only operational observation: completed calls for affected accounts; no new selection500 in sampled post-remediation window | [metadata](evidence/no-audio-live-recovery-observation.json), [log](evidence/no-audio-live-recovery-observation.log) |
| dialer-performance-backend | PASS | 0 | 220 backend units | [metadata](evidence/dialer-performance-backend.json), [log](evidence/dialer-performance-backend.log) |
| recovery-required-scale-gate | PASS | 0 | Required isolated scale wrapper;106k contacts /148k memberships /152k events | [metadata](evidence/recovery-required-scale-gate.json), [log](evidence/recovery-required-scale-gate.log) |
| recovery-incoming-existing-fixture | PASS | 0 | Reproduced earlier fixture failure and validated new incoming suite with preserved pre-existing synthetic caller | [metadata](evidence/recovery-incoming-existing-fixture.json), [log](evidence/recovery-incoming-existing-fixture.log) |
| recovery-real-dialer | PASS | 0 | Actual HTTP/PG reservations, callback priority, limits and concurrency | [metadata](evidence/recovery-real-dialer.json), [log](evidence/recovery-real-dialer.log) |

The optimized candidate SELECT was also executed **read-only** against the actual affected campaigns with hash/merge joins restored in that diagnostic transaction and JIT disabled locally:29.151ms /30.502ms,100 raw rows. It ran in a separate transient Python process, without installing code in the running application. First diagnostic harness quoting failed before execution; corrected retry and original failure are retained in `evidence/no-audio-optimized-source-live-readonly*`. Additional independent scale/unit before/after commands and genuine harness errors are in `evidence/dialer-candidate-20261114/{review.md,validation.json,scale-final-command.json}`.

The broader incoming UI remains covered by27 targeted browser PASS (its unchanged frontend). Fresh complete CI on this repair and image publication/provenance are **NOT TESTED at report creation**;7976734's failed run must not be used for deployment.

## Safe completion / removal of emergency tuning

1. Run complete Foundation CI and publication for the exact new main source. Deploy through the reviewed workflow when active calls have finished and chaining is paused. The server recovery already permits work; do not interrupt current calls to rush the UI patch.
2. Confirm healthy running revision equals that tested source. On fresh infrastructure, run the release's migrator command `python -m app.telephony.dialer_index ensure-index`; the live index already exists. The runtime role is refused maintenance. Existing invalid/incompatible indexes are rejected, never automatically dropped.
3. Execute the new API container command `python -m app.telephony.dialer_index restore-planner --expected-revision FULL_VERIFIED_RUNNING_SHA`. It refuses a different revision, missing optimized source, wrong DB role or changed/conflicting overrides. It resets only the three defaults that were previously unset. It does not terminate connections, change admission or originate calls. Pools pick up restored defaults as they recycle; transaction-local JIT remains scoped to selection.
4. Check fresh default-planner connections, next-call latency, callback priority, reporting/import latency and agent feedback. Keep the queue index. The previous application rollback would require retaining/reapplying the documented emergency tuning until the old selection is replaced.

The guarded reset is tested against synthetic roles and simulated release identity only; that is not release-provenance evidence. Current production defaults must stay in place until step2 succeeds.

## Residual status

- Immediate affected server selection: recovered as measured above; owner reports audio/calls restored.
- Charlotte still has separate `sdk_connect.unknown` browser failures after successful reservations, with no provider parent created. Her headset/browser check is pending; do **not** declare every agent fixed or infer a microphone root cause from the numeric diagnostics alone.
- This repair does not close native dependency, full disaster-recovery, live-carrier/20-agent mixed workload or browser-specific acceptance gates. Formal production certification remains **NO-GO** as documented in the wider audit.
- No final global release/deployment success is inferred from these targeted results.

## Exact recorded commands

### no-audio-live-readonly: PASS, exit 0

```sh
bash -c 'ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 - < qa-reports/evidence/no-audio-20261114/read-only.py'
```

### no-audio-live-queue-index: PASS, exit 0

```sh
bash -c 'ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 - < qa-reports/evidence/no-audio-20261114/add-queue-index.py'
```

### no-audio-candidate-after-index: FAIL, exit 1

```sh
bash -c 'ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 - < qa-reports/evidence/no-audio-20261114/plan-after-readonly.py'
```

### no-audio-candidate-jit-off: PASS, exit 0

```sh
bash -c 'ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 - < qa-reports/evidence/no-audio-20261114/plan-jit-off-readonly.py'
```

### no-audio-candidate-nested-probe: PASS, exit 0

```sh
bash -c 'ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 - < qa-reports/evidence/no-audio-20261114/plan-nested-readonly.py'
```

### no-audio-live-planner-remediation: PASS, exit 0

```sh
bash -c 'ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 - < qa-reports/evidence/no-audio-20261114/apply-runtime-planner.py'
```

### no-audio-live-restored-selection: PASS, exit 0

```sh
bash -c 'ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 - < qa-reports/evidence/no-audio-20261114/plan-inherited-readonly.py'
```

### no-audio-live-recovery-observation: PASS, exit 0

```sh
bash -c 'ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 - < qa-reports/evidence/no-audio-20261114/after-recovery-readonly.py'
```

### dialer-performance-backend: PASS, exit 0

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -e PYTHONDONTWRITEBYTECODE=1 -v /home/codexdev/unlimited-talk-qa-audit/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro -v /home/codexdev/unlimited-talk-qa-audit/scripts:/scripts:ro unlimited-talk-qa-audit:dependency-hardened python -m unittest discover -s /tests -p 'test_*.py' -v
```

### recovery-required-scale-gate: PASS, exit 0

```sh
env QA_API_IMAGE=unlimited-talk-qa-audit:dependency-hardened 'FOUNDATION_COMPOSE_ARGS=-p ut-recovery-20261114 -f /home/codexdev/unlimited-talk-qa-audit/compose.yaml -f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/recovery-20261114/compose.qa.yaml' python3 tests/verify_dialer_candidate_scale.py
```

### recovery-incoming-existing-fixture: PASS, exit 0

```sh
env 'FOUNDATION_COMPOSE_ARGS=-p ut-recovery-20261114 -f /home/codexdev/unlimited-talk-qa-audit/compose.yaml -f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/recovery-20261114/compose.qa.yaml' FOUNDATION_TEST_URL=http://127.0.0.1:18314 python3 qa-reports/evidence/recovery-20261114/verify-incoming-existing-contact.py
```

### recovery-real-dialer: PASS, exit 0

```sh
env 'FOUNDATION_COMPOSE_ARGS=-p ut-recovery-20261114 -f /home/codexdev/unlimited-talk-qa-audit/compose.yaml -f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/recovery-20261114/compose.qa.yaml' FOUNDATION_TEST_URL=http://127.0.0.1:18314 python3 tests/verify_dialer.py
```


### Online index / guarded reset: PASS, exit 0

Real isolated PostgreSQL verifies runtime-role denial, two idempotent migrator runs, wrong-release reset denial, matching-source restoration and changed-settings refusal. Simulated identity is local test context, not provenance.

```sh
env 'FOUNDATION_COMPOSE_ARGS=-p ut-recovery-20261114 -f /home/codexdev/unlimited-talk-qa-audit/compose.yaml -f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/recovery-20261114/compose.qa.yaml' FOUNDATION_TEST_URL=http://127.0.0.1:18314 python3 tests/verify_dialer_queue_index.py
```

[Recorder](evidence/recovery-index-and-reset-final.json), [log](evidence/recovery-index-and-reset-final.log).
