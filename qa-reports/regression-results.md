# Regression and release-validation results

Latest follow-up: [remaining automatic pause paths](dialer-pause-followup-20261112.md) distinguishes live log evidence, real-SDK regression, isolated controller/browser tests and unresolved provider/database-root-cause checks.

12 November follow-up: see [automatic dialer validation](dialer-autopause-20261112.md) for fresh commands, exit codes and evidence. Its browser tests use isolated HTTP/SDK fixtures; do not substitute them for the real HTTP/PG gates below.

Statuses distinguish PASS, FAIL, BLOCKED and NOT TESTED. A source review/build is not a user-journey pass. Provider media is simulated; business APIs/PG are real in the named end-to-end gates.

## Accepted execution by boundary

| Boundary | Status | Exit | Evidence |
|---|---|---|---|
| Foundation | PASS | 0 | [clean-foundation.json](evidence/clean-foundation.json) · [log](evidence/clean-foundation.log) |
| Identity/MFA/roles | PASS | 0 | [clean-identity.json](evidence/clean-identity.json) · [log](evidence/clean-identity.log) |
| Imports/broker/recovery | PASS | 0 | [post-dispatch-imports-retry-20261108T232036007187.json](evidence/post-dispatch-imports-retry-20261108T232036007187.json) · [log](evidence/post-dispatch-imports-retry-20261108T232036007187.log) |
| Fast consumer / durable lease | PASS | 0 | [post-dispatch-race.json](evidence/post-dispatch-race.json) · [log](evidence/post-dispatch-race.log) |
| Campaigns | PASS | 0 | [final-campaigns.json](evidence/final-campaigns.json) · [log](evidence/final-campaigns.log) |
| Calendar | PASS | 0 | [final-calendar.json](evidence/final-calendar.json) · [log](evidence/final-calendar.log) |
| Callbacks | PASS | 0 | [final-callbacks.json](evidence/final-callbacks.json) · [log](evidence/final-callbacks.log) |
| Reconfirmation/handoff14 | PASS | 0 | [final-backend-reconfirmation.json](evidence/final-backend-reconfirmation.json) · [log](evidence/final-backend-reconfirmation.log) |
| Signed outgoing voice | PASS | 0 | [hardened-voice.json](evidence/hardened-voice.json) · [log](evidence/hardened-voice.log) |
| Inbound follow-up | PASS | 0 | [final-inbound.json](evidence/final-inbound.json) · [log](evidence/final-inbound.log) |
| Automatic dialer | PASS | 0 | [final-dialer.json](evidence/final-dialer.json) · [log](evidence/final-dialer.log) |
| Call budgets7 | PASS | 0 | [final-call-budgets.json](evidence/final-call-budgets.json) · [log](evidence/final-call-budgets.log) |
| Reporting | PASS | 0 | [final-reporting.json](evidence/final-reporting.json) · [log](evidence/final-reporting.log) |
| Incoming reports6 | PASS | 0 | [final-reporting-incoming.json](evidence/final-reporting-incoming.json) · [log](evidence/final-reporting-incoming.log) |
| Incoming signed HTTP/PG /20-agent admission | PASS | 0 | [hardened-incoming-runtime.json](evidence/hardened-incoming-runtime.json) · [log](evidence/hardened-incoming-runtime.log) |
| Browser main65 +3 separately gated | PASS | 0 | [post-dispatch-browser.json](evidence/post-dispatch-browser.json) · [log](evidence/post-dispatch-browser.log) |
| Real outgoing browser/API/PG2 | PASS | 0 | [final-agent-workflow.json](evidence/final-agent-workflow.json) · [log](evidence/final-agent-workflow.log) |
| Real incoming browser/API/PG1 | PASS | 0 | [hardened-incoming-browser.json](evidence/hardened-incoming-browser.json) · [log](evidence/hardened-incoming-browser.log) |
| Schema guards | PASS | 0 | [hardened-schema.json](evidence/hardened-schema.json) · [log](evidence/hardened-schema.log) |
| Actual preceding runtime rollback | PASS | 0 | [hardened-rollback.json](evidence/hardened-rollback.json) · [log](evidence/hardened-rollback.log) |
| Backup/restore incl7incoming tables | PASS | 0 | [final-contacts-restore.json](evidence/final-contacts-restore.json) · [log](evidence/final-contacts-restore.log) |
| DB outage/recovery | PASS | 0 | [final-recovery.json](evidence/final-recovery.json) · [log](evidence/final-recovery.log) |
| Nginx ingress | PASS | 0 | [final-webhook-ingress.json](evidence/final-webhook-ingress.json) · [log](evidence/final-webhook-ingress.log) |

Unit/controller/build commands and all10 fresh populated migration gates are individually recorded in [the ledger](evidence-ledger.md). Repeated runs are not added together as unique tests. Named method counts and final browser JSON statistics are summarized in coverage-summary.md.

## Preserved failed attempts and rationale

- Baseline image build initially referenced frontend/dist excluded by .dockerignore. QA harness copied built web into a permitted temporary context. The failed build and successful retry both remain. Incremental QA images reuse a cached dependency base, not a clean production-build claim.
- Initial coverage startup hook lacked a mounted coverage package; recorded warnings were corrected in QA-only instrumentation. Pure-Python tracing caused health-check timeout overhead; the compatible musllinux C tracer restored the healthy lab. No application health assertion was relaxed.
- First call-budget fixture seeded a forbidden zero counter:7fixture errors, retained. Corrected absence means zero; seven real tests then reproduced six application failures, followed by seven passes.
- Foundation first lacked FOUNDATION_TEST_PROJECT for the isolated name; explicit-project and clean-lab reruns retain all original assertions. Initial identity last-admin check used a lab containing other audit-created administrators; a separate fresh database passed the unchanged identity suite.
- Main browser first execution:62PASS/3FAIL/3SKIP. Import exposed a real dispatcher race; inbound login used an expired fixture TOTP (read-only cryptographic proof in frontend evidence); failed-logout fixture omitted the incoming-session request. Presence404 observations exposed incomplete mock contracts. Fixtures were corrected to actual API200JSON and strict unknown-call assertions; no backend OTP/authorization boundary or browser assertion was weakened.
- Interrupted backend/source-loaded tests during service recreation/recovery remain BLOCKED in scoped notes. They are not application passes or newly confirmed defects.
- Rollback initially detected a changed fingerprint during a concurrent QA fixture run. Exact overlapping UTC/row-count proof is in security/rollback-concurrent-fixture-proof.json. An exclusive repeat preserved the original complete fingerprint and added per-table diagnostics; both phases pass with no app fix or weakened assertion.

- Re-running imports exposed the original fixture’s fixed phone already present from the first successful run. The fixture now chooses a verified unused synthetic phone and random session tokens; all original crash/duplicate/history assertions remain. The raw failed rerun and successful repeat are preserved.
- A clean Docker build was attempted but failed with exit1 because the local audit disk filled. Only its own failed intermediate container was removed; no user images/volumes were pruned. The later GitHub clean build and complete Foundation CI passed; the earlier local failure is retained.
Failure screenshots/traces: evidence/browser-artifacts/main (initial), evidence/browser-artifacts/recheck (repair run), evidence/frontend/*-artifacts (original focused reproductions). ZIPs are retained locally and ignored by Git; CI uploads new browser diagnostics on failure. Successful selected desktop/mobile screenshots are under evidence/screenshots.

## Reproduction

Synthetic lab arguments, image build, frozen-source manifests and commands are in tools/ and the ledger. Never use these outage/restore/race fixtures against production or managed databases. New drivers require DB_HOST=db, communicationsdisabled and an explicitly isolated project. Full browser runs use ephemeral local HTTPS and guarded fixture processes.

The original aggregate driver remains FAIL when any of its original gates failed; accepted focused/full repair reruns are shown independently. No failed evidence is deleted or relabelled.

## Independent clean GitHub validation

Foundation CI **PASS** for code commit `e09d9e496440d333a6433c595b2bf6d46cc66e85`: [run42537634865](https://github.com/climatsynergie/unlimited-talk/actions/runs/42537634865). All test-job steps succeeded; publish was skipped. Exact commands are in `.github/workflows/ci.yml` at that commit; public run/job/step evidence is preserved in `evidence/github-ci-run-final.json` and `github-ci-jobs-final.json`. Process exit codes are not exposed by that API and are not invented. The local equivalents have actual exit codes in the ledger.

CI log archive download was **BLOCKED**, HTTP403, due to missing log-download authorization. No authentication bypass was attempted. The run conclusion and individual step states were retrieved successfully. Main remained662b450; no deploy/merge/publish occurred.

The initial failed aggregate, failed fixtures, read-only coverage-dataset collection error and local disk-space build failure remain preserved. Their successful corrections/replacements are linked independently. Passing compatibility rollback verifies schema/data preservation, not that the older application contains the new security fixes; production needs a reviewed hardened fallback or patch-forward/admission-isolation plan.

## Native refresh re-execution — 9 November

[Fresh execution ledger](native-refresh-validation.md) records every local command/exit and fresh QA-branch CI step. A local clean build failed for disk capacity and remains preserved; a remote clean build is evaluated independently. Prior source's green CI is not used as proof for the new pins. Public CI metadata reports step conclusions, not numeric shell exits or raw individual-test counts. The [carrier plan](real-call-acceptance-plan.md) contains no executed-call PASS.
