# VM Hunter pilot: observation only

This optional integration is **not activated or deployed** by the normal release.
It does not create, redirect or hang up calls. The existing browser-first
`Dial/Number` flow and its recordings, status callbacks and automatic dialer
remain unchanged. A successful, signed `in-progress` child callback can request
an observation only when a separate private pilot configuration is present.

The business selected `CHIN LIST 514_REGION`
(`2bdf5195-0b52-49b1-aecc-0caaf5459e77`). The announcement name provided is
**Maisonverte Québec**. The announcement is not played in this observation
release: agents and clients continue talking normally. Screening before agent
connection, with the announcement, is a subsequent call-flow acceptance gate.

## Boundaries

- `pilot.example.json` is inactive and contains no agent IDs or test numbers.
- An enabled pilot requires 1–2 explicit agents, 1–10 consenting test numbers,
  audio-processing approval, and a total budget of 1–1000 analyses (default 500).
- Match campaign **and** agent **and** test number **and** automatic answered call.
  Manual calls and incoming calls never enter this pilot.
- PostgreSQL rechecks active campaign, active user and current assignment.
- A transaction claims each intent once; a shared admission lock enforces the
  pilot budget and at most two pending observations. Counts are conservative:
  claims consume local budget even when the provider never starts or bills.
- No new database schema or migration. Append-only `voice_events` stores only
  claim IDs and normalized results. Phone states, recordings, contact flags,
  campaign stages, pause counts and conversation metrics are not altered.
- The sidecar starts **inbound audio on the PSTN child leg**, not the browser leg
  or mixed audio. It converts G.711 mu-law to signed 16-bit little-endian mono
  PCM at 8kHz. Audio is bounded to 3.5 seconds; the provider deadline is 5 seconds.
- Quota/authentication errors, silence, ambiguity, disconnects and malformed
  data cannot hang up or pause a call. Even a confident machine verdict only
  produces an observation with `action=continue`.
- The sidecar's only Twilio writes create/stop **Streams**. No call creation or
  call update requests exist in it. Standard API key authentication is used;
  no new account Auth Token is requested.
- Stream creation is never retried. An ambiguous response is reconciled by
  unique stream name. Explicit stop runs on success, failure and orderly shutdown.
  Unconfirmed stop opens a local circuit: new observations are skipped while
  ordinary calling remains available. Operators must investigate that warning.
  PostgreSQL also blocks new claims after an unconfirmed stop or stale unfinished
  claim, so restarting the process cannot silently reset the circuit. Resume
  requires reviewed recovery after the provider's stream stop is verified;
  automatic circuit reset is deliberately not implemented in this pilot.
- Both internal dispatch and WebSocket start need short-lived, purpose-separated
  signed capabilities. Media must match the account, child call and stream.
  Tickets live in custom parameters, not URLs. Replay cannot start a second
  analysis. This does not claim Twilio account-token handshake validation.
- No audio, transcripts, key, capability, provider response body or customer
  number is logged. Call-screening phrases are normalized without preserving
  their contents. VM Hunter itself may retain submitted audio under its terms.

## Before any real pilot

1. Resolve processing geography and approval. The cloud service's published DPA
   states US hosting. The user has not yet confirmed audio processing approval.
   No customer audio may be submitted based on an ambiguous answer.
2. Choose the agents and consenting test numbers; verify headset and reception
   are working. Keep the production customer list out of the first tests.
3. Prepare private files from the inactive example and the root-stored API key;
   never put credentials in Git, command arguments, public mounts or chat.
   Container secrets must be readable by UID 10001 with private permissions;
   the enclosing host directory remains root-only. No preparer has run yet.
4. Complete CI, image/provenance checks, call drain, rollback review, egress and
   resource checks. Normal guarded deployment does not install this optional
   overlay; an explicit reviewed deployment change is still necessary.
5. Verify public TLS and WebSocket Upgrade for exactly
   `/api/telephony/vmhunter/media`; no Basic Auth may block Twilio's stream.
   `/private/observe` must stay internal. Do not expose the sidecar port.
6. The sidecar needs verified-TLS egress only to VM Hunter and Twilio Streams.
   Existing API egress needs only the internal `vmhunter:8080` RPC endpoint.
   Verify firewall rules; do not relax existing gateways globally.
7. Validate actual Standard-key Streams permissions, real stream track direction,
   explicit stream stopping and metering. Local mocks do not prove those.

`compose.observer.yaml` is a reviewed-input candidate, not a one-line activation
instruction. It is combined with the managed compose file from the release root.
The default managed compose file remains unchanged. Stopping the optional
observer and removing `VMHUNTER_PILOT_FILE` disables new observations. Drain its
pending jobs before stopping it. If stopped abruptly, inspect Twilio for orphan
streams and stop them explicitly; memory-only cleanup cannot run after SIGKILL.

## Controlled acceptance

| Scenario | Automatic local proof | Real participation needed |
| --- | --- | --- |
| Cloud config, binary PCM, verdict, deadline, cancellation | Loopback WebSocket tests | Actual account/key validity and classification accuracy |
| Scope, permissions, idempotency, budget, concurrent admission | Disposable PostgreSQL proof | Confirm chosen agents/lines in real account |
| Silence, beep, voicemail, call-screening assistant | Synthetic verdict tests, always continue | Consenting French/Québécois and English speakers, real voicemail |
| Provider/socket/auth/quota failure | Loopback failure tests | Approved controlled provider outage/egress test |
| Child audio, recording and ordinary dialer continuity | Existing HTTP/PG regression + browser mocks | Hear both directions, inspect recording and provider stream billing |
| Two simultaneous agents | DB transaction race + sidecar tests | Two headsets and two consenting phones |
| Twenty agents / customer campaign / transfers | Not in pilot scope | Separate capacity and feature acceptance |

Start with a live person, voicemail, silent answer, busy/no-answer and one
screening assistant; then repeat with two agents together. Record call/intent
references, expected label, observed label, decision latency, stream stop state,
recording availability and any impact on next-call progression. A human listens
and labels the sample. All calls continue normally, including predicted machines.
Stop the pilot for lost audio, agent auto-pause, unconfirmed stream stop,
unacceptable delay or unexplained usage. Do not infer live accuracy from mocks.

Only after that evidence should screening be developed/accepted. Twilio's
`Number url` does not support `Start/Stream`; the existing call cannot simply
receive the vendor's customer-first example. The greeting also changes caller
speech timing; VM Hunter's API guide recommends no prompt during analysis.
Verify that tradeoff with real volunteers before automatic hangups are enabled.

Primary references (retrieved 2026-11-24):

- https://vmhunter.com/docs/api
- https://vmhunter.com/docs/twilio (vendor labels its bridge Beta)
- https://vmhunter.com/dpa
- https://www.twilio.com/docs/voice/api/stream-resource
- https://www.twilio.com/docs/voice/media-streams/websocket-messages
- https://www.twilio.com/docs/voice/twiml/number
