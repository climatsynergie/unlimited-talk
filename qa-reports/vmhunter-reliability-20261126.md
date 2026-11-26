# VM Hunter recovery and application-wide campaign rollout — 26 November 2026

## Owner request and initial findings

Investigate the apparent cessation of filtering and INITIALSILENCE results before extending to the full application. Read-only managed history and runtime checks confirmed a real reliability defect: at 21:48 UTC on 25 November, two Twilio Stream create requests timed out. Their stop/recovery requests were also unconfirmed while the corresponding calls were still live. The worker set a permanent in-memory degraded flag; the database also retained unresolved cleanup facts. Later terminal call callbacks did not retry the authenticated terminal read, so analysis never resumed. Calling stayed available. At discovery the worker was alive/healthy but `accepting=false`.

Evidence: `evidence/vmhunter-live-history-20261126.{json,log}`, exact read-only command and exit 0. Of 150 INITIALSILENCE results in the investigated period, 147 had explicit continue decisions (145 human_or_uncertain, one unavailable_or_pending, one caller_input); three had no screening decision. None had a filter hangup decision. Only confident MACHINE/MACHINE_BEEP are rejected with confirmed cleanup. The provider MACHINE label alone does not describe this application's action. The classification sample also contained HUMAN and confident MACHINE results; it does not establish audio accuracy or the cause of the high silent share.

Official reference: https://www.vmhunter.com/docs/api defines INITIALSILENCE as no speech in the analysis window, including silent answers/no audio. It does not prove a human, nor a voicemail. No raw recordings or transcripts were retrieved for this investigation.

## Minimal repair

The independent worker now performs bounded account-scoped cleanup recovery on startup and every 15 seconds. It reads only the exact authenticated provider Call, verifies account/SID/terminal status, then requires matching stored claim nonce, pilot, child SID, account and terminal database state before appending `vmhunter.cleanup_verified`. Existing results and call/CRM state are never rewritten. Live, unknown, foreign, missing, timeout and unverified states cannot clear the circuit. Multiple supervisors append the same proof idempotently. The worker resumes only when no unresolved claims remain. Recovery also discovers stale claims after process interruption. No database migration is required.

Health adds cleanup_pending and active_analyses. Analysis results optionally store validated bounded integer PCM-byte, frame and signal-frame counters, without audio content or transcripts. Signal energy is a diagnostic, not speech or human classification; INITIALSILENCE continues unchanged.

The campaign operator now accepts an explicit list on the existing v4 policy, preserving quota configuration and dynamic agent membership, and verifies each selected campaign is active, dialer-enabled and has active assigned agents. Discovery identified 11 currently eligible campaigns. Their explicit IDs are in `evidence/vmhunter-reliability-20261126/approved-active-campaigns.json`. Archived campaigns, manual calling and incoming reception remain outside this outbound automatic screening policy. New future campaigns are not a wildcard opt-in. Both previously selected and newly selected campaigns share the Free 5,000/month quota and two-analysis capacity; excess simultaneous analysis admission bypasses filtering rather than delaying or dropping ordinary calls.

## Executed evidence

Every named evidence JSON records exact command, source/diff hash, timestamps, log hash and exit code. No real phone call was originated.

| Check | Result | Exit | Evidence |
| --- | --- | --- | --- |
| Same regression on committed pre-fix observer | FAIL, expected reproduction: missing recovery, circuit stays set | 1 | `evidence/vmhunter-recovery-reproduction-20261126.json` |
| Backend suite after repair, 328 tests | PASS | 0 | `evidence/vmhunter-recovery-backend-release-20261126.json` |
| Host/operator boundaries, 40 tests | PASS | 0 | `evidence/vmhunter-recovery-host-20261126.json` |
| Disposable PostgreSQL: delayed terminal proof, concurrency/idempotency, binding, unchanged history/schema and audio counters | PASS | 0 | `evidence/vmhunter-recovery-postgres-final-20261126.json` |

Two initial focused local attempts failed to import `app` after the working directory was changed to `/tests`; these harness failures are preserved as `vmhunter-recovery-before-fix` and `vmhunter-recovery-unit` records. The corrected invocation explicitly set PYTHONPATH; it reproduced the actual absent recovery and then passed with the fix. No failing assertion was removed.

## Deployment and limits

PENDING: exact-source worker CI, signed image verification, isolated worker rollout, explicit eleven-campaign scope activation and independent live checks. The primary API should remain revision35, with unchanged container start time; no API restart is needed for this extension. Normal protected API deployment guards are unchanged. Real carrier audio, provider accuracy, a 17–20-agent all-filtered capacity test, and browser UI testing of this server-only change are NOT EXECUTED. Wider existing production certification blockers remain; this scoped repair does not certify the entire app as defect-free.
