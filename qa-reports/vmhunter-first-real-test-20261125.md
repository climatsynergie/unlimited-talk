# VM Hunter first real test — 25 November 2026

The owner initiated the test as Oumayma agent on CHIN LIST. QA/release tools did
not originate any phone call. At 16:52 UTC the optional sidecar, narrow /32 HTTPS
egress, exact media proxy, private API policy mount and automatic provider DNS
refresh were installed. Provider authentication/synthetic silence, public WSS,
negative authentication and runtime checks actually passed (see activation logs).
Those checks did not prove PSTN streaming or voicemail filtering. The initial
claim that the test was ready overstated the available evidence.

## Actual real-call failure

- First automatic call `c48f1435-41c4-483c-bdfe-32ec54f71e77` had a screening
  snapshot but no analysis result. Its decision was `continue/bypass`.
- Next automatic call `fd04d4bc-8d25-464f-95b0-c36767f0c859` acquired a claim,
  then recorded `FAILED/stream_unavailable`, unconfirmed stream stop. The shared
  circuit disabled further analyses as designed. No successful real provider
  classification or voicemail filtering is claimed.
- The user's label for the first call is voicemail. It was passed through because
  screening failed to start, not because an observed classifier called it human.
- Subsequent ordinary calls continued. The agent paused her own dialer. Only the
  VM policy was then disabled in place; ordinary calls stayed enabled and the
  API was not restarted. All original events/results are preserved.

Evidence: `evidence/vmhunter-activation-20261125/agent-monitor-corrected.log`,
activation/probe recorder files, and captured tool results. The first auxiliary
monitor query used nonexistent `pause_reason`; this was corrected to actual
schema fields. Its failed output is retained, not treated as an application bug.

## Confirmed API-contract defect and repair in QA

A read-only GET to the real Streams collection returned HTTP405/error20004.
The cleanup implementation used that unsupported GET/list operation to reconcile
an uncertain stream creation. Twilio documents create and stop; stop accepts the
specific stream SID or its name:
[Twilio Streams reference](https://www.twilio.com/docs/voice/api/stream-resource).
The replacement stops only the unique owned name using POST, verifies SID/name/
call/status, and leaves ambiguous 404 cleanup blocked. It never creates another
stream or updates/hangs up a Call. New loopback regressions failed before and
passed after the repair. Existing wrong GET assumptions were corrected to the
observed provider contract, with stronger exact-method/path assertions.

New diagnostics retain only HTTP status and numeric provider error code, or
exception type/SQLSTATE for admission errors. Keys, capabilities, provider bodies,
customer audio/numbers/transcripts are not logged.

Verified terminal-call cleanup is append-only: `vmhunter.cleanup_verified` can
release an old safety circuit only when the stored intent is terminal and the
proof matches its exact child call SID, claim nonce and terminal provider status.
An unmatched nonce cannot clear it. The root recovery operator must independently
verify the real provider call is terminal before writing evidence; no historical
failed result is changed or deleted.

## Remaining diagnosis limits

The original stream-create HTTP error was discarded by the old implementation.
Its exact error code has not been recovered. A separate safe probe on the already
terminal call returned 400/21220 (expected terminal-call error); that does NOT
prove the original live request failed for the same reason. No call was created.

Twilio's Number whisper permits only Say/Play/Gather/Hangup; Twilio's help index
also notes media is not yet established during a whisper. This suggests a
pre-bridge media constraint in the chosen flow, but it is not yet a captured live
HTTP diagnosis. Do not present an inferred cause as proven or the repaired cleanup
as successful machine detection:
[Number reference](https://www.twilio.com/docs/voice/twiml/number),
[Twilio whisper recording limitation](https://help.twilio.com/articles/33597761542683-How-to-Record-a-Call-Whisper-in-a-Call-Recording).

## Release strategy and status

The web/API application remains on attested 36a451a, manual calls enabled.
The VM worker gets its own narrowly scoped build/test/provenance pipeline from
that pinned base. This allows verified worker repair without replacing the API
or interrupting the other agents. This is not permission to bypass provenance.

Executed local evidence: 307 backend tests PASS after the HTTP repair; 28 host
operator tests PASS; disposable PostgreSQL lease/budget/verified-cleanup proof
PASS; pre-bridge surrounding proof is recorded when completed. Exact commands,
exit codes and hashes are in the per-check JSON/logs under evidence/.

Current verdict: **FAIL for the first real filtering test; NO-GO for broad VM
filter activation.** Normal application calls remain available. Real audio,
classification, cleanup and next-call acceptance require another controlled test
once the targeted worker is verified; existing synthetic checks are not a PASS
for that test. Inherited native-library findings remain open.
