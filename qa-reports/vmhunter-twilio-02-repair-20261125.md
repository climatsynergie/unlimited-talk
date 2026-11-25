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
