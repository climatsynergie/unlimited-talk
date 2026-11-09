# Coverage summary

Measured Python application line/branch coverage from instrumented synthetic unit, HTTP/API/PG, browser and recovery executions. This is code coverage, not percentage completion or proof of correctness. SQL predicates and React TSX browser branches are not measured by this metric.

- Executed Python statements: **4774/5210 (91.63%)**.
- Executed Python branches: **1363/1770 (77.01%)**.
- No coverage exclusions were introduced to raise the result. Raw coverage.json/coverage.txt include missing lines and arcs. Celery prefork children may not all flush; functional broker/worker assertions remain separate evidence.

## Critical Python modules

| Module | Lines | Branches |
|---|---|---|
| identity/service.py | 188/199 | 61/70 |
| calendar/routes.py | 148/152 | 37/44 |
| campaigns/language.py | 52/68 | 19/36 |
| contacts/dispatch.py | 24/26 | 6/6 |
| telephony/incoming_runtime.py | 80/85 | 30/40 |
| telephony/incoming_hooks.py | 95/97 | 52/58 |
| telephony/dialer_service.py | 106/120 | 48/68 |
| telephony/service.py | 190/206 | 91/106 |
| reporting/service.py | 84/85 | 21/22 |

## Frontend controller unit coverage

Node native experimental coverage for controller units only, excluding TSX/browser executions:

```text
# start of coverage report
# -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# file                     | line % | branch % | funcs % | uncovered lines
# -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# frontend                 |        |          |         |
#  src                     |        |          |         |
#   incoming-controller.ts |  85.87 |    62.64 |   75.68 | 141-144 172 176-181 185-190 202-208 226-228 250-255 259-261 285-286 289-295 319-322 346-348 352 427-430 449-451 477-480 491-496 499-504 507-517 604-605 621-622
#   phone-controller.ts    |  92.29 |    80.08 |   86.05 | 169-172 199-200 204-205 265-272 282-283 352-358 391-397 433-437 494-499 691-694 697-699 704-707 841-842 845-855 904-909
# -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# all files                |  89.69 |    72.94 |   81.25 |
# -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# end of coverage report
```

Exact run: [controller coverage command/log](evidence/final-controller-coverage-retry-20261108T232501298774.json). Browser lifecycle and real API/media-adapter journeys add execution that is not included in this Node-unit metric. There is no measured whole-frontend coverage percentage.

## Execution counts and interpretation

- Python unit suite:208 named tests (including3 runtime dependency-policy regressions). Host suite:8. Controller suite:52 named tests (repeated runs are not additional unique tests).
- New real PG/HTTP regression methods:14 appointment/language,7budgets,6incoming reporting,6dispatcher races. These are included in integration gates, not counted a second time as unit tests.
- Main browser suite declares68 cases; three synthetic-provider cases are intentionally gated there and must independently execute as2outgoing +1incoming real-API/PG gates. Initial main result62PASS/3FAIL/3SKIP is preserved. Final repair result and JSON statistics are in regression-results.md.
- Ten fresh populated migration gates executed through schema12. Other integration scripts contain multiple assertions and concurrency/failure scenarios; their command counts are not invented individual test counts.

## Reproducibility and remaining gaps

Coverage7.17.2 runs through a QA-only .pth hook with the compatible musllinux native tracer. Final container/image identities are recorded across API replacement. Source fingerprints prove the final image matches all64 application Python files. Earlier compatible-image coverage is retained only for unchanged files; its superseded contacts/dispatch.py data is discarded before combining. Unrelated baseline/fixture processes are excluded by image/hostname provenance, not by whether their lines were covered. See [inputs.json](coverage/inputs.json) for source versions, every selected file hash and ignored datasets.

Commands: `python3 qa-reports/tools/coverage_containers.py` while executing guarded gates; stop QA Python services gracefully to flush; `/tmp/ut-qa-audit-tools/bin/python qa-reports/tools/combine_coverage.py`; `/tmp/ut-qa-audit-tools/bin/python qa-reports/tools/render_coverage.py`. Installation and native-wheel versions are in evidence. Raw process files remain local and are ignored by Git.

Residual gaps include actual media/token/network behavior on real devices; provider outage/retry timing; distributed call latency; all endpoint/input permutations; every modal/keyboard/screen-reader/browser combination; adversarial filter/navigation/upload interruptions beyond the existing cases. Uncovered branches are review targets, not automatically defects or implicitly waived acceptance gates. See test-matrix.md and release-readiness.md for BLOCKED/NOT TESTED boundaries.
