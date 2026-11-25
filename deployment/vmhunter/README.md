# VM Hunter: observation and pre-agent screening

## Release update — 25 November 2026

The owner has explicitly approved the provider's disclosed US audio processing
and requested all currently assigned agents and contacts in CHIN LIST 514_REGION.
This resolves the earlier geography/scope questions below, which remain as
historical evidence. It does not establish actual audio quality or classification
accuracy. The owner delegated the safest rollout choice: install the screened
runtime dormant, then verify human/voicemail calls with a participating agent
before broad activation. No call is originated by the release operator.

`campaign.screen.example.json` is a separate **version 3** policy. It is disabled
by default. Explicit campaign scope requires empty pilot allowlists, separate
audio/screening approval, the same fixed campaign ID and the same bounded budget.
Live PostgreSQL joins check the active campaign, active assigned agent, active
contact membership and exact canonical destination before reserving/claiming an
analysis, and again before any rejection. New assignments/members are included;
removals take effect without copying customer lists into configuration files.
Manual/incoming/other-campaign calls remain excluded. Version 1/2 pilot limits
are unchanged. Two concurrent analyses and the finite analysis budget remain
safety bounds: excess calls connect normally without being filtered. This is
not evidence that all concurrent customer calls will be screened.

Real-call acceptance, optional sidecar installation, key/Streams permissions,
public WSS and cleanup/metering checks are still activation requirements.
Inherited native-library findings are not cleared by this functionality update.

Both modes are disabled by default. The normal application deployment does not
install the optional overlay or supply an enabled private policy. Incoming and
manual calls are excluded. No database migration is introduced.

`pilot.example.json` retains version-1 observation, described in the historical
section below. `pilot.screen.example.json` adds version-2 screening with separate
`audio_approved` and `screening_approved` booleans. The inactive example has no
selected agents or numbers. Both modes require the intersection of campaign,
1–2 selected agents and 1–10 consenting test numbers. PostgreSQL rechecks current
assignment, active users and campaign, transactional budget and concurrent jobs.

## Screening call flow

1. The committed reservation adds a `Number url` whisper to the original Dial.
   `answerOnBridge` keeps the agent on ringing until it finishes. Recordings,
   callbacks, caller selection and the 30-minute limit stay with that Dial.
2. A signed account/parent/child-bound webhook requests analysis from the private
   sidecar. Missing service, admission limits and provider cooldown bypass the
   greeting and connect normally.
3. The client hears **« Bonjour, ici Maisonverte Québec. Un conseiller vous répond
   dans un instant. »**, followed by a one-second DTMF wait. The whisper uses
   supported `Gather`/`Say` verbs; no unsupported `Start/Stream` or `Pause`.
4. The signed result rejects only `MACHINE/MACHINE` or `MACHINE/MACHINE_BEEP`
   with confirmed cleanup, an unchanged approved policy and a decision window
   younger than eight seconds. Human, silence, MAXWORD, noise, screening
   assistants, disconnect tones, unknown causes, auth/quota errors, missing
   results and any caller DTMF (including `#`) connect normally. Late results
   cannot reverse an already released decision.
5. Verified machines use the existing voicemail disposition, excluded from
   answered-conversation and talk totals. The pipeline becomes `Pas de réponse`
   only if no newer human edit, appointment, callback or restriction wins.
   Filtering does not pause the dialer; the usual ten-second wrap-up applies.

There is no REST call creation, redirect or hangup. Only the signed whisper can
return `Hangup` on the approved child. Manual pause/stop remains authoritative.
No broad browser SDK error suppression was added: actual SDK behavior needs
real-call acceptance.

The sidecar samples only the PSTN child's inbound audio. Audio is bounded to
3.5 seconds, the provider deadline to five seconds and the whole job to nine
seconds. A stale screening result cannot reject after eight seconds. These
bounds do not promise a particular live connection delay.
The window starts at the first observed PSTN answer or whisper, not at the
reservation: a long ringing period does not expire it. If a DB outage prevented
screen-start from being recorded, the ordinary answer still recovers after the
bounded window; a delayed start cannot reopen screening after that recovery.

Provider auth/quota/subscription errors add a 30-second admission cooldown;
other failed analyses add two seconds. Calls bypass the filter during cooldown.
Unconfirmed stream cleanup and stale claims also retain the existing durable
orphan circuit across restarts. Review/stop orphan streams before recovery;
SIGKILL cannot run in-memory cleanup. Keys, raw audio, transcripts, capabilities
and provider response bodies are not added to application logs.

## Activation and rollback gates

- Resolve processing geography and consent: the published cloud DPA states US
  hosting. The answer about Canada is still ambiguous; do not transfer customer
  audio on that basis.
- Choose agents and consenting test numbers; complete current CI/provenance,
  security review and explicitly authorized guarded deployment during call drain.
- Use private files readable by UID 10001 and a root-private enclosing directory.
  The optional overlay mounts exactly five secrets, runs non-root/read-only,
  and has no published sidecar port. Never put keys in Git, arguments or chat.
- Verify TLS egress, real key permissions, metering and public WSS at exactly
  `/api/telephony/vmhunter/media`. Keep `/private/observe` internal.
- Signed POST routes `screen-start/{uuid}` and `screen-result/{uuid}` under
  `/api/telephony/twilio/` must pass the perimeter. Optional
  `public-routes.caddy` narrows the exceptions; never exempt the whole app.
- Complete human/voicemail/silence/screening-assistant trials first with one
  agent, then two concurrently. Listen both ways, inspect recordings, measure
  greeting/connection delay, verify stream stopping and the next call without
  auto-pause. Synthetic verdicts do not establish real accuracy or SDK behavior.
- Native-library security blockers remain documented in QA reports. Automated
  functionality checks are not a production GO decision.

To disable new screening, replace the private policy with its disabled example
or remove `VMHUNTER_PILOT_FILE`. Keep services/keys available until pending jobs
and calls drain. Disabling during a whisper releases it at its next decision.
Verify no orphan streams before stopping the sidecar or rolling back the image.
Preserve append-only events: no destructive schema downgrade is needed.

Real acceptance must be separately authorized. Stop on lost audio, an erroneous
human rejection, auto-pause, orphan stream or unacceptable delay/usage. The
requested greeting changes speech timing; VM Hunter recommends no prompt during
analysis. That tradeoff requires volunteers and human labels, not just mocks.
Two-agent simulations do not prove capacity for 17–20 real agents or transfers.

## Historical version-1 observation notes

The following describes the preceding observation-only build. Statements about
unimplemented screening apply to version 1; version 2 above implements it but
has not passed real-call acceptance or production activation gates.

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
