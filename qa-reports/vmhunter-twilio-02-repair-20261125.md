# Live Twilio 0.2.0 handshake incompatibility — 25 November 2026

## Confirmed defect

**High severity for VM Hunter filtering; ordinary calling remains enabled.**

The owner initiated an automatic CHIN LIST 514_REGION call as Oumayma agent at 18:38:16 UTC, intent `5b6dbd7d-0bde-4ccf-86f2-015562d7691a`. She heard ringing and hung up. Application history records `no-answer`; this UI/outcome alone does not establish whether the remote PSTN leg answered during pre-bridge processing. The actual worker received a connected frame with both expected event and protocol, but protocol version **0.2.0**. The application only allowed **1.0.0**, the version in the current Twilio documentation example. It rejected the frame before ticket validation/audio classification. The job timed out, saved `FAILED/stream_unavailable`, and opened its cleanup safety circuit. No filtering success is claimed for that call.

Actual diagnostic:

```
vmhunter_connected_rejected event_matches=True protocol_matches=True version=0.2.0
vmhunter_media_rejected phase=connected_frame type=ProtocolError ticket_present=False
vmhunter_stream_failure phase=classification_wait type=TimeoutError stream_known=True media_connected=False
```

Evidence: `evidence/vmhunter-twilio-02-live-diagnosis-20261125.{json,log}` and `evidence/vmhunter-oumayma-focused-real-test-20261125.log`. The latter is the finite read-only monitor; an exit 0 from the monitor means the observer ran, not that the phone acceptance test passed.

## Minimal repair

Accept exactly the observed **0.2.0** and previously supported **1.0.0** connected-frame versions. Preserve expected event/protocol, short handshake deadline, signed capability, exact account/call/stream binding, codec checks, bounded audio, stop verification, campaign membership, call dispositions and recordings. An unknown future version still fails closed at the media boundary and leaves the ordinary call flow available.

Add a loopback HTTP/WebSocket regression which uses the actual 0.2.0 handshake, sends signed/bound synthetic media, obtains a provider verdict, verifies one confirmed cleanup and no degraded circuit. Add a regression that an unsupported 2.0.0 version cannot consume the valid admitted job; the normal 1.0.0 connection then completes. Switch the full signed-HTTP/PostgreSQL screening proof's Twilio simulator to 0.2.0; normal 1.0.0 coverage remains in unit tests.

## Executed checks

| Result | Executed command / evidence | Outcome |
| --- | --- | --- |
| FAIL before fix (expected regression reproduction) | `python3 qa-reports/tools/run_check.py vmhunter-twilio-02-regression-before-20261125 -- sudo -n docker run ... python -m unittest discover -s /tests -p test_vmhunter_observer.py -v` | 13 tests, 1 failure, exit 1. New real-version regression returned FAILED instead of MACHINE; exact full command and source diff hash are in the JSON evidence. |
| PASS after fix | `python3 qa-reports/tools/run_check.py vmhunter-twilio-02-regression-after-20261125 -- sudo -n docker run ... python -m unittest discover -s /tests -p test_*.py -v` | 310 tests, exit 0. Exact full command/raw output/hash in the corresponding JSON/log. |

PostgreSQL screening proof and attested worker CI/deployment evidence will be appended after execution. No real phone calls are originated by test/deployment tooling. CVC MTL has not been enabled, as requested by the owner. API remains on 36a451a; only the independently attested worker is a deployment target for this fix.

## Acceptance status

**Real voicemail/human audio acceptance: NOT YET PASSED.** The observed handshake defect is reproduced and repaired in local tests; another owner-initiated call is required after verified worker deployment. A synthetic MACHINE verdict does not prove real voicemail accuracy or two-way human audio.

## Additional executed evidence

- **PASS:** isolated PostgreSQL + signed HTTP + WebSocket screening/recovery proof, exit 0. Command: `python3 qa-reports/tools/run_check.py vmhunter-twilio-02-screen-postgres-20261125 -- env FOUNDATION_COMPOSE_ARGS='-f /home/codexdev/unlimited-talk-vmhunter-release/qa-reports/evidence/vmhunter-release-20261125/compose.json' VMHUNTER_USE_LOCAL_SOURCE=1 python3 tests/verify_vmhunter_screen.py`. Evidence: `evidence/vmhunter-twilio-02-screen-postgres-20261125.{json,log}`. Actual output: 19 safe decisions, 22 simulated analyses, two-agent continuation, recording/disposition contracts, explicit pause/stop, deadline and database-outage recovery; zero real calls. The commit was created while the check ran, without changing source files during execution; CI below verifies the immutable built source independently.
- **PASS:** VM Hunter Worker CI run [45677691315](https://github.com/climatsynergie/unlimited-talk/actions/runs/45677691315), exact source `263208d1e92e2e296aca672c26f4c204e6b8b451`: all 11 steps successful. Stored API evidence: `evidence/vmhunter-activation-20261125/worker-twilio-02-ci-jobs.json`. Includes built-image unit suite, disposable PostgreSQL screening, lease/budget/verified-cleanup proof, image publication and provenance attestation. This is component CI, not overall application certification.
- **PASS:** root worker image provenance verification for 263208d, exit 0. Exact recorded SSH command: `evidence/vmhunter-twilio-02-worker-provenance-20261125.{json,log}`. Only the independently verified worker is being updated; application revision remains 36a451a.

## Deployed correction and pre-test gates (18:44 UTC)

- **PASS:** independently attested worker 263208d installed, exit 0, `evidence/vmhunter-twilio-02-worker-rollout-20261125.{json,log}`. Worker digest `sha256:40e1020a1917fd1e1711721b6b5b0b42b9f02125e240bf4e97e1948ca5a04d05`. Four historical failed claims have terminal provider-call cleanup proofs; no historical result was changed. API remains 36a451a, not restarted, ordinary calling enabled.
- **PASS:** actual Store admission queries extracted from the deployed worker and executed read-only: no unresolved stream cleanup, 22 claims out of 500 budget, zero active analyses, accepting=true, exact worker revision 263208d. CHIN LIST only; CVC MTL excluded. Command: `python3 qa-reports/evidence/vmhunter-activation-20261125/check-twilio-02-pretest-gates.py`, recorded exit 0 in `evidence/vmhunter-twilio-02-pretest-admission-20261125.{json,log}`. Claim count is not the provider's count of completed audio analyses.
- **PASS:** health, internal unauthenticated-RPC rejection, public unsigned-screen rejection, hidden private RPC and unauthenticated calls rejection. Command: `python3 qa-reports/evidence/vmhunter-activation-20261125/verify-activation.py`, recorded exit 0 in `evidence/vmhunter-twilio-02-postupdate-runtime-20261125.{json,log}`.

**Ready for an owner-initiated diagnostic retest; real filtering remains NOT YET VERIFIED.** Do not claim the application or provider pilot production-certified from these gates.

## Owner retest at 18:51 UTC — genuine unanswered call

Intent `3b3057ef-d5ef-423f-bbef-4199a269a57b`, Oumayma agent, automatic CHIN LIST 514_REGION, created 18:51:12 UTC and finished 18:51:54 UTC. The owner heard ringing only; this time she did not report pressing hangup. Read-only application timeline has screening eligibility but no `screen.started`, analysis claim, result or decision. No media job or connected-frame rejection appears in the deployed worker log.

- **PASS (read-only evidence collection only):** `python3 qa-reports/evidence/vmhunter-activation-20261125/check-oumayma-postfix-retest.py`, recorder exit 0, `evidence/vmhunter-oumayma-postfix-retest-20261125.{json,log}`. Application state finished, outcome no-answer.
- **PASS (provider status verified):** `python3 qa-reports/evidence/vmhunter-activation-20261125/verify-last-retest-provider-status.py`, recorder exit 0, `evidence/vmhunter-postfix-retest-provider-status-20261125.{json,log}`. Verified-TLS GET of the exact bound Twilio child call confirms matching account and call SID, provider status `no-answer`, duration `0`. No call was created or modified.
- **PASS (expected no-answer behavior):** no VM classification was launched for a provider-confirmed unanswered call. This explains ringing followed by automatic completion; it does not establish human/voicemail detection accuracy.
- **NOT TESTED in this retest:** live answered Twilio 0.2.0 media, provider classification, verified live-stream stop after a verdict, real voicemail rejection, real two-way human audio. No post-fix real filtering success is claimed.

Next acceptance input must be an answered automatic campaign call, labelled by the owner as a human or voicemail. Keep CVC MTL excluded. Do not perform another deployment merely because an unanswered call ended.
