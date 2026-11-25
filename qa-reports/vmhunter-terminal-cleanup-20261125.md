# VM Hunter — terminal-call cleanup reliability, 25 November 2026

**Filtering acceptance remains incomplete.** This report separates the repaired handshake, the actual first provider result, and the cleanup circuit defect revealed by the next test. The owner initiated all real calls. CVC MTL remains excluded.

## Real test evidence (18:58–18:59 UTC)

Oumayma agent's automatic CHIN LIST 514_REGION intent `2b9238ad-1cae-4b5e-83bb-90016df2fd3b` now passed the repaired 0.2.0 media handshake. The worker persisted an actual provider result `MACHINE / INITIALSILENCE`, `action=continue`, `stream_stop_confirmed=false`. INITIALSILENCE is uncertain and must never be treated as confirmed voicemail or used to reject a human. No amount or quality of received customer audio is inferred merely from that provider result.

The exact authenticated Twilio Call GET confirms `completed`, duration **1 second**, with matching account and child SID. A subsequent safe stop probe, performed only after independently verifying this same call was terminal, returned **HTTP400 / 21220**. This is a captured terminal-call API contract; the original live stop response was not logged and must not be claimed recovered.

The unresolved cleanup fact opened the in-memory/durable analysis safety circuit. The next two calls (`925dd95c-770b-46f1-8dfc-22f7dd29e77b`, `218ce96f-44db-491b-8f52-186da904ab53`) continued normally with `continue/bypass`, no analysis, recordings archived. Neither is a filtering success. The owner's human/voicemail ground-truth label is pending.

Executed evidence (exact commands, timestamps, exit codes and hashes in matching JSON files):

- `python3 qa-reports/evidence/vmhunter-activation-20261125/check-oumayma-postfix-retest.py` — exit 0, evidence collection only; `evidence/vmhunter-oumayma-next-retest-20261125.{json,log}`.
- `ssh ... root@143.198.41.24 docker logs --since 15m --tail 160 unlimited-talk-vmhunter-vmhunter-1` — exit 0, log collection only; `evidence/vmhunter-next-retest-worker-log-20261125.{json,log}`.
- `python3 qa-reports/evidence/vmhunter-activation-20261125/verify-analyzed-retest-provider-status.py` — exit 0, bound provider terminal state confirmed; `evidence/vmhunter-analyzed-retest-provider-status-20261125.{json,log}`.
- `python3 qa-reports/evidence/vmhunter-activation-20261125/check-owned-terminal-stream-stop.py` — exit 0, confirmed-terminal owned stream stop contract captured; `evidence/vmhunter-owned-terminal-stop-contract-20261125.{json,log}`. No Call resource was created or updated.

## Confirmed defect and minimal repair

A finished call can race the stream-stop POST. The worker had no authenticated terminal-call fallback, so one fast hangup disabled later analyses until a root operator manually verified terminal cleanup. Confirmed production evidence is the already-terminal call, failed cleanup fact and subsequent bypasses; the regression reproduces this exact failure-recovery scenario.

After a failed stream stop/recovery, read only that exact Call over authenticated, verified TLS, with a two-second deadline and redirects disabled. Require exact account SID, exact child SID and one known terminal status (`completed`, `busy`, `no-answer`, `failed`, `canceled`). A verified terminal Call cannot retain a billable live stream, so its cleanup is confirmed. An active/unknown/foreign/missing call, authentication error, redirect, malformed reply or read timeout leaves the safety circuit intact. This does not enable Call writes or weaken human-preservation decisions.

## Executed regression results

- **FAIL before fix, expected reproduction:** 14 observer tests, one failure, exit 1. New `test_verified_terminal_call_does_not_open_cleanup_circuit` observed `stop_confirmed=false`. Exact Docker command and raw failure: `evidence/vmhunter-terminal-cleanup-regression-before-20261125.{json,log}`.
- **PASS after fix:** complete isolated backend unit suite, **314 tests**, exit 0. Exact Docker command and raw result: `evidence/vmhunter-terminal-cleanup-regression-after-20261125.{json,log}`. Covers terminal status/account/SID binding, live/unknown states, missing/auth/error replies, redirects, read timeout, preserved circuit on uncertainty and continued 0.2.0/1.0.0 handshake support.

The signed-HTTP/PostgreSQL proof additionally simulates a callee ending during classification, verifies persisted cleanup and an unblocked next analysis. Its execution result, component CI and deployment gates will be recorded after they complete.

**Real voicemail rejection and human two-way audio: NOT YET VERIFIED.** No production certification is claimed from synthetic tests or a silence verdict.

## PostgreSQL + signed HTTP/WebSocket execution

- **FAIL (fixture daily-attempt budget):** the first expanded proof completed the new terminal-call scenario, then a later fixture call was rejected at the existing Dial assertion. This run added another call to the first synthetic contact, which already approached its configured 20-attempt daily budget. Evidence retained: `evidence/vmhunter-terminal-cleanup-postgres-20261125.{json,log}`, exit 1. No production setting or assertion was changed.
- **PASS:** run the two additional sequential recovery cases on the second existing synthetic agent/contact, within its unchanged attempt budget. Command: `python3 qa-reports/tools/run_check.py vmhunter-terminal-cleanup-postgres-second-agent-20261125 -- env FOUNDATION_COMPOSE_ARGS='-f /home/codexdev/unlimited-talk-vmhunter-release/qa-reports/evidence/vmhunter-release-20261125/compose.json' VMHUNTER_USE_LOCAL_SOURCE=1 python3 tests/verify_vmhunter_screen.py`. Exit 0; full evidence in the matching JSON/log. Actual output includes `terminal_cleanup_keeps_next_analysis=true`, 24 simulated provider analyses, preserved explicit pause/stop, two-agent concurrency and zero real calls. The proof ends the call during a gated classification, persists confirmed cleanup, then analyses the same agent's next call. Unknown cleanup still opens the circuit in the subsequent original test.

Component CI and live deployment are pending at this report revision. Real filtering acceptance remains incomplete; do not equate an INITIALSILENCE verdict with voicemail.

## Installed worker and executed live read-only verification (19:12 UTC)

- **PASS:** exact built source `44f5a760dbbaa9cef1b1e3681c8ae9f03bb79db9`, [VM Hunter Worker CI 45682099971](https://github.com/climatsynergie/unlimited-talk/actions/runs/45682099971), all 11 steps successful. Includes 314 backend tests, PostgreSQL screening/recovery proof, budgets/leases and image provenance. Stored step results: `evidence/vmhunter-activation-20261125/worker-terminal-cleanup-ci-jobs.json`.
- **PASS:** `ssh ... root@143.198.41.24 python3 /usr/local/sbin/unlimited-talk-vmhunter-worker-release verify 44f5a760dbbaa9cef1b1e3681c8ae9f03bb79db9`, recorder exit 0; `evidence/vmhunter-terminal-cleanup-worker-provenance-20261125.{json,log}` records the complete command, digest and provenance checks.
- **PASS:** same command with `rollout`, recorder exit 0; `evidence/vmhunter-terminal-cleanup-worker-rollout-20261125.{json,log}`. Worker image digest `sha256:2645e5f2f9d8ceab8793a60b9c1702ccf09ded0b3a674ca8fb1482c7fa6dca8a`. API stayed on 36a451a and was not restarted; ordinary calling remained enabled. Historical failed results retained; verified terminal-call cleanup remains append-only.
- **PASS:** deployed new `Streams.call_finished` executed against the original real one-second call, not a mock: exact bound Twilio Call GET plus the deployed new helper both confirm completed. Command: `python3 qa-reports/evidence/vmhunter-activation-20261125/verify-new-terminal-helper-real-call.py`; recorder exit 0 in `evidence/vmhunter-terminal-helper-real-call-proof-20261125.{json,log}`. No call originated or Call resource updated.
- **FAIL (operator verification timeout):** initial post-rollout admission proof exceeded its unchanged 25-second Docker-exec wrapper while two Python verification processes ran in parallel in the resource-bounded worker. No successful admission check was claimed from it. Evidence: `evidence/vmhunter-terminal-cleanup-pretest-admission-20261125.{json,log}`. The exact reason for the timeout was not instrumented; CPU contention is an inference, not an established cause.
- **PASS:** rerun the same admission proof sequentially, with the same assertions, SQL deadlines and wrapper timeouts: `python3 qa-reports/evidence/vmhunter-activation-20261125/check-terminal-cleanup-pretest-gates.py`; exit 0 after 16.8 seconds, `evidence/vmhunter-terminal-cleanup-pretest-admission-sequential-20261125.{json,log}`. Exact revision matches; no unresolved cleanup, 23/500 claims, zero active analyses, accepting=true. Claims are not completed provider analysis counts. CHIN LIST only; CVC MTL excluded.
- **PASS (read-only diagnostic collection only):** original call's Twilio Notifications GET returned HTTP200 with an empty notification list; `evidence/vmhunter-analyzed-call-notifications-20261125.{json,log}`. This does not prove audio quality or absence of every provider problem.

The owner reports one human saying hello, one message asking the caller to say their name, and three unanswered calls across her tests. Those labels are not individually correlated to intent IDs. A recipient's call-screening message is an uncertain case and must continue to the agent; no rejection is claimed for it. The retrieved analysed intent returned INITIALSILENCE, while the following two retrieved answered intents bypassed analysis under the old safety circuit. Their archived recordings and the owner's heard audio are not evidence that VM filtering passed.

**Status: ready for an owner-initiated diagnostic retest on Oumayma agent / CHIN LIST 514_REGION. Real confident voicemail rejection, correctly passed human audio under active analysis, and subsequent automatic continuation still require acceptance evidence. Overall production-readiness certification remains NO-GO.**
