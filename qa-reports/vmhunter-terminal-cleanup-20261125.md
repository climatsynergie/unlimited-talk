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
