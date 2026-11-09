# Native refresh executed validation

Snapshot: 2026-11-09T19:58:03.404103+00:00. QA source: `405dc5a611da7795ecac85b7302c54702502e9b8`.

## Local executions

| Check | Result | Exit | Exact command | Evidence |
|---|---|---:|---|---|
| native-refresh-host-units | PASS | 0 | `python3 -m unittest discover -s tests/host -p 'test_*.py' -v` | [native-refresh-host-units](evidence/native-refresh-host-units.log) |
| native-refresh-controller-units | PASS | 0 | `sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -v /home/codexdev/unlimited-talk-qa-audit/frontend:/web:ro -w /web node:22-alpine@sha256:0e1754758c2df4cfa3e68d59e2e1b7374bb7fd9ea6328eaaacf15cc934af8202 npm run test:phone` | [native-refresh-controller-units](evidence/native-refresh-controller-units.log) |
| native-refresh-ingress | PASS | 0 | `python3 tests/verify_webhook_ingress.py` | [native-refresh-ingress](evidence/native-refresh-ingress.log) |
| native-refresh-npm-audit | PASS | 0 | `npm --prefix frontend audit --json` | [native-refresh-npm-audit](evidence/native-refresh-npm-audit.log) |
| native-refresh-compose-validation | PASS | 0 | `sudo -n docker compose config --quiet` | [native-refresh-compose-validation](evidence/native-refresh-compose-validation.log) |
| native-refresh-production-build | FAIL | 1 | `sudo -n docker build --build-arg GIT_REVISION=qa-native-20261109 -t unlimited-talk-qa-audit:native-refresh .` | [native-refresh-production-build](evidence/native-refresh-production-build.log) |
| native-refresh-apk-selected-gate | FAIL | 1 | `python3 qa-reports/tools/native_refresh_scan.py` | [native-refresh-apk-selected-gate](evidence/native-refresh-apk-selected-gate.log) |

The local build failed for disk capacity. The selected APK scanner intentionally fails while zlib-origin advisory matches remain; its native scope/reachability is reviewed in native-library-review.md. Package scanner execution success is not whole-image clearance.

## Fresh CI steps

[QA-only Foundation CI](https://github.com/climatsynergie/unlimited-talk/actions/runs/42685739475). Numeric shell exits and raw individual-test counts are unavailable via the public metadata API; no exit0 is invented. Exact declared commands and conclusions are retained in [ci-command-results.json](evidence/native-refresh/ci-command-results.json).

| Step | Status | CI conclusion |
|---|---|---|
| Generate disposable CI database credentials | PASS | success |
| Validate SSH secret formatting and key identity | PASS | success |
| Build the preceding compatibility release for rollback verification | PASS | success |
| Validate configuration and build image | PASS | success |
| Test database configuration guards | PASS | success |
| Install web verification dependencies | PASS | success |
| Install the tested Chromium headless shell | PASS | success |
| Verify Chromium runtime and install missing libraries if required | PASS | success |
| Verify additive migration preserves populated identity data | PASS | success |
| Verify campaign migration preserves existing contacts | PASS | success |
| Verify calendar migration preserves existing campaigns | PASS | success |
| Verify callback migration preserves appointments | PASS | success |
| Verify Voice migration preserves existing business data | PASS | success |
| Verify recording archive migration preserves Voice history | PASS | success |
| Verify inbound migration preserves CRM and Voice history | PASS | success |
| Verify dialer migration preserves call facts and CRM history | PASS | success |
| Verify long recording migration preserves existing history | PASS | success |
| Verify incoming migration preserves populated CRM and call history | PASS | success |
| Start disposable local environment | PASS | success |
| Verify HTTP, PostgreSQL and isolation | PASS | success |
| Verify identities, permissions and session revocation | PASS | success |
| Verify imports, transactional recovery and broker execution | PASS | success |
| Verify fast import consumer and durable dispatcher recovery races | PASS | success |
| Verify campaigns, permissions and concurrent pipeline moves | PASS | success |
| Verify shared calendar permissions and appointment transactions | PASS | success |
| Verify reconfirmation authorization and callback handoff regressions | PASS | success |
| Verify callback reservations and priority | PASS | success |
| Verify signed Voice API, durable reservations and concurrent replays | PASS | success |
| Verify inbound settings, manual follow-up and concurrent ownership | PASS | success |
| Verify automatic queues, callback ownership, regional callers and pause races | PASS | success |
| Verify authenticated call budgets and concurrent admission | PASS | success |
| Verify bounded public webhook ingress and authentication payloads | PASS | success |
| Verify malformed JSON resource bounds through the production gateway | PASS | success |
| Verify administrator reporting and Excel exports | PASS | success |
| Verify incoming reporting and Excel counters | PASS | success |
| Verify browser flows through local HTTPS | PASS | success |
| Verify real browser, API and PostgreSQL call-disposition workflow | PASS | success |
| Verify real incoming browser, API and PostgreSQL workflow | PASS | success |
| Verify additive schema readiness guards | PASS | success |
| Verify rollback preserves the identity schema and data | PASS | success |
| Verify synthetic contact backup and restore | PASS | success |
| Verify database outage and recovery | PASS | success |
| Verify incoming runtime upgrade, routing and private voicemail on disposable PostgreSQL | PASS | success |
| Export the tested image | NOT TESTED | skipped |
| Show service diagnostics | NOT TESTED | skipped |
| Stop disposable environment | PASS | success |

Earlier local coverage/test counts remain historical source evidence, not freshly measured native-image coverage. Live provider/media tests remain BLOCKED pending credentials, participants and explicit authorization. No real call is initiated by these scripts.
