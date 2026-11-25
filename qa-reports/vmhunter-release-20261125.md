# VM Hunter release integration — 25 November 2026

The owner authorized deploying both incoming appointment context and voicemail
screening code after stopping calls. Incoming context dc44e0f was deployed and
verified separately at 16:06 UTC (70 Python source hashes, READY schema12, manual
calling enabled). Original guard failures remain recorded in its isolated worktree.

The owner now explicitly approves the disclosed US processing and requests all
agents and contacts in CHIN LIST 514_REGION. They delegated the rollout choice.
Chosen approach: deploy the combined, tested code dormant; complete a controlled
human/voicemail audio check before enabling broad automatic hangups. No agent or
customer call is originated by these release tools. Dormant code installation
is not active filtering, a real telephony PASS, or overall production certification.

## Scope and maintained behavior

This integrates committed VM runtime 05a8809 with current live UI/API dc44e0f.
The incoming client-sheet/appointment features and prior telephony fixes remain.
Version 3 campaign policy explicitly opts into every active assigned agent and
current campaign contact, with authoritative membership/phone checks before
claiming and rejection. Version 1/2 pilot restrictions are unchanged. Manual,
incoming and other-campaign calls retain their existing paths. Two concurrent
analyses and finite 1–1000 budget remain; excess traffic connects normally.
No new schema or migration. Appended voice events are readable by prior schema12
code. Call-drain, deployment lock, OCI provenance, rollback and manual calling
restoration remain required. No operator guard is relaxed.

## Executed checks

Commands, actual exit codes, source diff fingerprints and SHA-verified logs are
in `evidence/vmhunter-release-20261125/validation-manifest.json` and each recorder
JSON/log. Local API source is mounted read-only over the canonical prior QA image;
this does not replace fresh exact-source main CI or cryptographic OCI proof.

- Unit suite: 305 tests PASS, exit 0.
- New campaign-scope regression: failed on the old pilot parser (ProtocolError),
  passed after explicit version-3 implementation; no assertion weakened.
- Signed HTTP/PostgreSQL/provider-loopback screening: PASS, exit 0; 22 synthetic
  analyses, safe results, actual expiry, two simultaneous jobs, manual pause/stop,
  campaign third-agent admission, exclusion/revocation, machine reporting and
  next-call continuation. Zero real calls. Not a real-agent capacity proof.
- Phone controller: 175 tests PASS, exit 0.
- Frontend build and formatting: PASS, exit 0.
- Appointment context HTTP/PostgreSQL: 5 tests PASS, exit 0.
- Voice, dialer, inbound and incoming runtime HTTP/PostgreSQL checks PASS, exit 0.
  Incoming proof includes synthetic three-/20-agent concurrent admission.

Invocation failures are retained: an initial recorder argument was misordered
(exit127, no test run), and a coordinator referenced nonexistent
`tests/verify_incoming.py` (exit2, no incoming test run). Corrected actual inbound
and incoming-runtime checks executed successfully. Neither failure is reported
as an application defect or replaced by a fabricated PASS.

## Activation and residual risks

BLOCKED / not verified: real key classification, actual Twilio Streams permissions,
public WSS/media-track behavior, bilingual human/voicemail false positives, real
audio/recordings, greeting latency, metering and stream stop. A participating agent
and consenting phones are required. No real acceptance or live audio transfer is
claimed. Optional sidecar and public perimeter routes must be installed/reviewed
before activation; ordinary deployments do not activate them implicitly.

Inherited native Expat/OpenSSL findings in the preceding QA report remain open;
this release does not clear them or establish overall security GO. The packaged
OpenTelemetry API patch 1.45.2 is included. Full final CI/provenance/deployment and
post-release results will be appended only after execution.

Current status: pending remaining browser validation and fresh main CI; no VM
filter activation. General production-readiness NO-GO remains separate from the
owner-authorized scoped operational release.
