# Controlled VM Hunter acceptance and CHIN LIST rollout

## Confirmed owner decisions

- Company greeting: Maisonverte Québec.
- Disclosed US processing: explicitly approved on 25 November 2026.
- Ultimate scope: all active agents and contacts of CHIN LIST 514_REGION.
- Read-only snapshot: 17 active assigned agents; 15,842 active contact memberships.
  Counts describe the query time, not a fixed allowlist or capacity benchmark.
- Owner delegated the safest option. Chosen rollout: dormant code deployment,
  bounded real-human/voicemail acceptance with a participating agent, then
  campaign scope. No real call was initiated by the release tooling.

## Before any audio transfer

1. Use the exact CI-passed, attested image and unchanged guarded deployment.
2. Install/review optional sidecar, private UID10001-readable credentials/policy,
   internal RPC and narrow public signed hooks/WSS route. Keep policy disabled.
   The current standard managed deployment intentionally does not install these.
3. Provide dedicated, constrained verified-TLS egress for the sidecar; do not
   open the current application's entire restricted network. Current API-container
   probes to VM Hunter/Twilio timed out. This is an unresolved transport gate.
4. Verify actual key/subscription and Twilio Streams permissions with the owner;
   key storage alone is not proof of validity. Keep secrets out of logs/chat/Git.
5. Keep current calls available. Perimeter reloads must validate before reload;
   API replacement still requires idle calls and paused dialers. Retain rollback.
6. Review residual native-security findings. This operational change does not
   establish overall production/security GO.

## Safe first calls (requires human participation, not automated origination)

Use a volunteer who explicitly agrees to receive the test call and have the
short audio processed. Do not choose random production customers as test data.
First use the version-2 policy with one agent and consenting number. Automatic
calls qualify; manual and incoming calls deliberately bypass screening.

To target the consenting contact using existing application behavior, the
participating agent can arrange a due callback for that campaign contact and
verify it is the next eligible priority callback before starting the chain.
Pause/stop the chain before another customer is attempted. Do not bypass call
reservations, invent dialer ownership or alter real customer state through SQL.
If the exact volunteer destination cannot be verified safely, do not start.

| Case | Expected result | Human evidence |
| --- | --- | --- |
| French/Québécois live answer | Client hears approved short greeting, then reaches agent; never machine rejection | Listen both directions; label outcome; measure greeting and bridge delay |
| English live answer | Same connection behavior, no false rejection | Both participants confirm audio |
| Ordinary voicemail and beep | Confirmed machine may be rejected; voicemail counter once; no talk/answered inflation | Compare provider/CRM result, recording, next-call state |
| Silent answer / background noise | Connect normally; silence alone cannot reject | Human label and actual connection |
| Caller presses # or another key | Connect even when classifier says machine | Capture signed outcome and hear bridge |
| Busy / no answer / bad number | Existing ordinary behavior and wrap-up; no unwanted auto-pause | Agent observes next-call progression |
| Provider auth/quota/timeout | Filter bypass/cooldown; calls continue normally | Approved controlled failure; no secret disclosure |
| Pause / stop during screening | Never undone; next call stays paused/stopped | Agent observes controls |
| Two agents / separate volunteers | Independent calls, audio and cleanup; no cross-contact fiche | Both agents confirm |

Record call/intent references privately, human expected label, normalized result,
decision time, stream stop confirmation, recording availability, voicemail/talk
counters and agent continuation. No raw audio/transcript in QA reports. No live
agent-transfer feature is implemented by this filter or asserted as tested.

## Campaign activation and stop conditions

Only after successful real acceptance use version3 scope=campaign. Empty pilot
allowlists are intentional: current active assignment/contact/phone membership
is checked in PostgreSQL before claim and rejection. Manual/incoming/other
campaign calls remain excluded. Keep the initial finite analysis budget and
two-job concurrency cap until real billing/capacity evidence supports expansion;
overflow connects normally. Thus not every simultaneous call is guaranteed to
be filtered. Do not market two-job mocks as 17-/20-agent real acceptance.

Stop new filtering on lost audio, any false human rejection, unwanted auto-pause,
unconfirmed stream cleanup, unacceptable delay or unexplained usage. Disable
new admissions, drain pending jobs and verify/stop provider orphan streams before
stopping sidecar/rolling back. Preserve append-only events and schema12; no data
schema downgrade. Reboot, future deployment, calling-mode restore and sidecar
image/policy persistence must be checked before broad activation.

Status at preparation: automation PASS for synthetic protocol/API/DB/browser
scenarios; actual telephony/sidecar/perimeter/egress acceptance BLOCKED or NOT
TESTED as above. This plan is not a real-call test result.
