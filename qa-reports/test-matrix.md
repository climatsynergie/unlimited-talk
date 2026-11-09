# Risk-based QA matrix

PASS: executed assertions satisfied. FAIL: executed assertions failed. BLOCKED: a prerequisite prevents valid execution. NOT TESTED: not executed. A pass applies only to the stated scope.

| Area | Priority | Boundary | Status | Evidence scope |
|---|---|---|---|---|
| AUTH | P0 | Login, MFA, invitations, password, expiry, roles and last admin | PASS | Real browser and HTTP/PostgreSQL; security units |
| CRM | P0 | CSV upload, preview, confirmation, deduplication and recovery | PASS | Real PostgreSQL, Redis/Celery and S3-compatible mock; real browser |
| DISPATCH | P0 | Immediate consumer, duplicate delivery, failed publication and lease recovery | PASS | Six deterministic PostgreSQL concurrency regressions |
| PIPE | P0 | Stages, notes, DNC/NI, English handoff and current-call context | PASS | Real HTTP/PostgreSQL and browser disposition workflows |
| RDV | P0 | Qualification, booking, reconfirmation, DST and atomic callback cancellation | PASS | 14 HTTP/PostgreSQL tests; real calendar UI; three reconfirmation UI cases |
| CALLBACK | P0 | Ownership, priority, rescheduling and history | PASS | Real HTTP/PostgreSQL, concurrency and browser failure recovery |
| OUT | P0 | Manual/automatic calls, wrap-up, hold, pause and voicemail | PASS | Two real browser/API/PostgreSQL journeys; simulated provider/media |
| IN | P0 | Reception, offers, answer, occupancy and missed follow-up | PASS | Real browser/API/PostgreSQL; separate simulated 3/20-agent admission |
| MEDIA | P0 | Signatures, replay, late callbacks, private archives and ranges | PASS | Local object store and fake provider HTTP; live provider blocked |
| REPORT | P1 | Live/day/hour reports, DST, Excel, voicemail and incoming metrics | PASS | Real PostgreSQL/XLSX and dashboard UI fixtures |
| UI | P1 | Routes, forms, keyboard, responsive layout, refresh and error states | PASS | 65 main cases plus three separately executed provider-fixture cases |
| ABUSE | P0 | Anonymous depletion, counter storage, session rotation and concurrency | PASS | Seven real HTTP/PostgreSQL regressions |
| INGRESS | P0 | Methods, bodies, timeouts, rate and resource limits | PASS | Actual Nginx; separate 64 oversized and 64 accepted-size malformed requests |
| RELEASE | P0 | Migration, compatibility rollback, restore and outage recovery | PASS | Ten populated migration gates, schema guard, restore and database outage |
| DEPENDENCIES | P0 | Native image patch status | BLOCKED | JavaScript/Python scans: zero matches; APK advisory gate requires patch/rescan or precise VEX |
| CAPACITY | P1 | CSV parser at 100,000 rows / 10 MiB / 512 MiB | PASS | One parse and two overlapping parses; full PostgreSQL import throughput not tested |
| CARRIER | P0 | Real headset audio, recording and 20 real agents | BLOCKED | No live provider writes or calls; database admission does not establish audio capacity |
| CLEAN BUILD / CI | P0 | Clean Docker build and complete Foundation CI | PASS | GitHub run42537634865, code commit e09d9e4; publication skipped |
| CLOUD RECOVERY | P0 | Managed failover, host/object restore and cloud IAM | BLOCKED | No destructive production operations; local database recovery is a separate test |
| EXHAUSTIVE INPUTS | P2 | Every input, browser/device and distributed slow-trickle combination | NOT TESTED | No blanket exhaustive-coverage claim |

Detailed commands and results: [regression results](regression-results.md), [coverage](coverage-summary.md), [security review](security-review.md), [evidence ledger](evidence-ledger.md).

Additional dynamic gaps include delayed campaign navigation/filter responses, every upload/unmount/lost-ack combination, all operating systems/headsets/mobile browsers, live SDK expiry and hardware permissions, managed provider retry timing and continuous distributed slow trickles. Selected failure paths are tested; every combination is not.

## Native refresh and real-call acceptance — 9 November

The compatible-image candidate is tested separately from the earlier application repair baseline. [Fresh validation](native-refresh-validation.md) distinguishes executed PASS/FAIL and pending/not-tested CI steps. Package-only scans cannot establish complete native-component clearance. [Real-call acceptance matrix](real-call-acceptance-matrix.md) maps automation, credentials and human participation; all carrier/media scenarios remain unexecuted. Live audio transfer is unsupported.
