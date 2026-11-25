# VM Hunter live diagnostics — 25 November 2026, 18:16 UTC

**Real-call acceptance: FAIL. Filtering is not operational.** Ordinary calling remains enabled. The provider dashboard count of one analysis was reported by the owner; its attribution to a particular call is NOT VERIFIED.

## Executed evidence

- PASS — `python3 qa-reports/tools/run_check.py vmhunter-diagnostics-provenance-20261125 -- ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes root@143.198.41.24 python3 /usr/local/sbin/unlimited-talk-vmhunter-worker-release verify dd33331ad40c448e3b01f6ad3db76fdb734cb0d9` — exit 0; exact source/provenance verified. Evidence: `evidence/vmhunter-diagnostics-provenance-20261125.{json,log}`.
- PASS — same recorded SSH command with `rollout` instead of `verify` — exit 0. Worker changed to dd33331; API remained 36a451a; API not restarted; ordinary calls enabled. Evidence: `evidence/vmhunter-diagnostics-worker-rollout-20261125.{json,log}`.
- FAIL — first Charlotte snapshot harness: SQL string quoting error. Preserved in `evidence/vmhunter-charlotte-diagnostic-snapshot-20261125.{json,log}`. This was a QA script error, not an application defect.
- PASS (read-only snapshot execution only) — corrected `python3 qa-reports/evidence/vmhunter-activation-20261125/check-charlotte-diagnostics.py` via recorder — exit 0. Charlotte dialer running, generation 790. Two recent calls completed; neither has a successful VM result. Evidence: `evidence/vmhunter-charlotte-diagnostic-snapshot-20261125-retry-20261125T181548801309.{json,log}`. This is not a filtering acceptance pass.
- PASS — complete isolated backend unit suite: 308 executed tests, exit 0. Exact Docker command, source working-diff hash and raw output: `evidence/vmhunter-connected-diagnostics-backend-20261125.{json,log}`. Mocks are not proof of live provider behavior.

## Live failure observed

Read-only worker logs at 18:16:07 UTC show:

```
vmhunter_media_rejected phase=connected_frame type=ProtocolError ticket_present=False
vmhunter_stream_failure phase=classification_wait type=TimeoutError stream_known=True media_connected=False
vmhunter_stream_unavailable
vmhunter_stream_stop_unconfirmed
```

The stream was created, but no authenticated media job connected before the bounded deadline. One inbound WebSocket was rejected at the connected-frame phase; its source is not yet independently established. Do not assume that frame is Twilio merely because it arrived during the call. No raw frames, capabilities, keys or audio were logged. A further bounded diagnostic records only expected-event/protocol booleans and a numeric semantic-version string to distinguish the first-frame failure without weakening validation.

The safety circuit bypasses further analyses when stream cleanup is unconfirmed. Ordinary calls remain available. The newly deployed diagnostics are not a functional filtering fix. No new phone calls were initiated by this audit.

## Remaining blockers

1. Establish the exact live connected-frame discrepancy and reproduce it with a regression test before changing the protocol boundary.
2. Demonstrate real Twilio audio reaches VM Hunter and produces a durable verdict with confirmed stream cleanup.
3. Verify voicemail rejection and a human call with two-way audio and automatic next-call continuation, using agent-initiated tests.
4. Confirm concurrency behavior and agent/customer experience before claiming campaign-wide filtering acceptance.

**VM Hunter release readiness: NO-GO.** Overall application production certification is not established by these component checks.
