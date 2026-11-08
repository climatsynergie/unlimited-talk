"""Conservative release report: only completed commands can satisfy a gate."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[2];reports=root/'qa-reports'
gates=json.loads((reports/'evidence/accepted-gates.json').read_text());by={x['boundary']:x for x in gates}
rows=[
('AUTH','P0','Login, MFA, invitations, password, expiry, roles and last admin','Identity/MFA/roles','Real browser and HTTP/PostgreSQL; security units'),
('CRM','P0','CSV upload, preview, confirmation, deduplication and recovery','Imports/broker/recovery','Real PostgreSQL, Redis/Celery and S3-compatible mock; real browser'),
('DISPATCH','P0','Immediate consumer, duplicate delivery, failed publication and lease recovery','Fast consumer / durable lease','Six deterministic PostgreSQL concurrency regressions'),
('PIPE','P0','Stages, notes, DNC/NI, English handoff and current-call context','Campaigns','Real HTTP/PostgreSQL and browser disposition workflows'),
('RDV','P0','Qualification, booking, reconfirmation, DST and atomic callback cancellation','Reconfirmation/handoff14','14 HTTP/PostgreSQL tests; real calendar UI; three reconfirmation UI cases'),
('CALLBACK','P0','Ownership, priority, rescheduling and history','Callbacks','Real HTTP/PostgreSQL, concurrency and browser failure recovery'),
('OUT','P0','Manual/automatic calls, wrap-up, hold, pause and voicemail','Real outgoing browser/API/PG2','Two real browser/API/PostgreSQL journeys; simulated provider/media'),
('IN','P0','Reception, offers, answer, occupancy and missed follow-up','Real incoming browser/API/PG1','Real browser/API/PostgreSQL; separate simulated 3/20-agent admission'),
('MEDIA','P0','Signatures, replay, late callbacks, private archives and ranges','Incoming signed HTTP/PG /20-agent admission','Local object store and fake provider HTTP; live provider blocked'),
('REPORT','P1','Live/day/hour reports, DST, Excel, voicemail and incoming metrics','Incoming reports6','Real PostgreSQL/XLSX and dashboard UI fixtures'),
('UI','P1','Routes, forms, keyboard, responsive layout, refresh and error states','Browser main65 +3 separately gated','65 main cases plus three separately executed provider-fixture cases'),
('ABUSE','P0','Anonymous depletion, counter storage, session rotation and concurrency','Call budgets7','Seven real HTTP/PostgreSQL regressions'),
('INGRESS','P0','Methods, bodies, timeouts, rate and resource limits','Nginx ingress','Actual Nginx; separate 64 oversized and 64 accepted-size malformed requests'),
('RELEASE','P0','Migration, compatibility rollback, restore and outage recovery','Actual preceding runtime rollback','Ten populated migration gates, schema guard, restore and database outage'),
]
lines=['# Risk-based QA matrix','','PASS: executed assertions satisfied. FAIL: executed assertions failed. BLOCKED: a prerequisite prevents valid execution. NOT TESTED: not executed. A pass applies only to the stated scope.','','| Area | Priority | Boundary | Status | Evidence scope |','|---|---|---|---|---|']
for code,priority,boundary,gate,scope in rows:lines.append(f'| {code} | {priority} | {boundary} | {by[gate]["status"]} | {scope} |')
lines += [
'| DEPENDENCIES | P0 | Native image patch status | BLOCKED | JavaScript/Python scans: zero matches; APK advisory gate requires patch/rescan or precise VEX |',
'| CAPACITY | P1 | CSV parser at 100,000 rows / 10 MiB / 512 MiB | PASS | One parse and two overlapping parses; full PostgreSQL import throughput not tested |',
'| CARRIER | P0 | Real headset audio, recording and 20 real agents | BLOCKED | No live provider writes or calls; database admission does not establish audio capacity |',
'| CLEAN BUILD | P0 | Clean release image, current GitHub CI and provenance | BLOCKED | Full build failed with exit1 because the local audit disk filled; matched-dependency QA image tested |',
'| CLOUD RECOVERY | P0 | Managed failover, host/object restore and cloud IAM | BLOCKED | No destructive production operations; local database recovery is a separate test |',
'| EXHAUSTIVE INPUTS | P2 | Every input, browser/device and distributed slow-trickle combination | NOT TESTED | No blanket exhaustive-coverage claim |',
'', 'Detailed commands and results: [regression results](regression-results.md), [coverage](coverage-summary.md), [security review](security-review.md), [evidence ledger](evidence-ledger.md).',
'', 'Additional dynamic gaps include delayed campaign navigation/filter responses, every upload/unmount/lost-ack combination, all operating systems/headsets/mobile browsers, live SDK expiry and hardware permissions, managed provider retry timing and continuous distributed slow trickles. Selected failure paths are tested; every combination is not.',
]
(reports/'test-matrix.md').write_text('\n'.join(lines)+'\n')
failed=[g for g in gates if g['status']!='PASS'];passing=len(gates)-len(failed)
remaining='\n'.join(f'- {g["boundary"]}: {g["status"]}; `{g["record"]}`.' for g in failed) or 'All selected local boundary gates pass after repair. Original failed attempts remain preserved.'
text=f'''# Release readiness

**Verdict: NOT READY for production release.**

The audit repairs confirmed defects and provides executable evidence. Native dependency review, a clean release-image build/CI and live carrier acceptance remain blocked. Production data, routing and deployment were not changed.

## Reviewed source and environment

- Baseline: main/deployed `662b450501a70431b0effbb087501e727111099d`; incoming candidate `96f5055b7fff29257a0e306e0658721394cc80a7`.
- Isolated branch: `qa/full-audit-20261108`. Exact application/image hashes: [source manifest](evidence/final-source-manifest.json).
- Tests use isolated PostgreSQL, Redis, an S3-compatible mock and synthetic Twilio fixtures with external communications disabled.
- Observed production was on schema11. Candidate schema12 still requires a controlled release; this audit does not activate incoming routing on the existing server.

## Validation

Accepted local boundaries: **{passing}/{len(gates)} PASS**. This is a gate count, not percentage completion. See [regression-results.md](regression-results.md) for the commands, exits and original failures.

{remaining}

Seven high application findings, five medium application findings and two low findings were repaired in the QA branch. The low findings concern documentation and reception-panel spacing. One additional high dependency release gate remains open. Conditional Critical vendor advisories are not represented as proven Critical application exploits. See [findings.md](findings.md).

## Required before release

1. **Resolve native image advisories.** Test patched/re-pinned images and rescan, or support each remaining issue with a narrowly justified VEX review. The gateway's latest tag resolves to the same affected digest, so pulling again alone cannot resolve this gate.
2. **Build and verify the release artifact.** Run the complete Foundation CI on the reviewed commit, then verify the published digest, revision and attestation. The local clean build failed with exit1 due to the audit workspace's disk limit. This is separate from production server capacity. A tested incremental QA image is not a clean, published release artifact.
3. **Complete carrier acceptance.** On a selected UT-only line, test real inbound/outbound calls, two-way headset audio, recording/archive/playback and missed-call/voicemail behavior. Progress from three to twenty real agents with measured latency/CPS and occupancy checks. Local synthetic admission and real browser/API/PostgreSQL flows already pass their stated scopes.
4. **Review credentials and cloud access.** Confirm previously exposed credentials were rotated/revoked. Verify line ownership/routing, Spaces permissions, trusted sources, IAM and monitoring. Live secret values are excluded from reports; retained traces can contain disposable synthetic credentials.
5. **Review complete-system recovery.** Verify managed PostgreSQL PITR/failover, object-storage restore/retention, host restore and secret/MFA-key recovery. Local database restore/outage tests do not establish full production disaster recovery.

## Residual limits

- Real PSTN quality, provider retry timing and hardware permissions remain **BLOCKED**.
- The parser passed the advertised 100,000-row / exact10-MiB bound within512MiB. Full PostgreSQL import throughput and mixed20-agent workload were **NOT TESTED**.
- Every endpoint/input permutation, browser/screen-reader/device combination, distributed slow-trickle attack and navigation/lost-ack combination was **NOT TESTED**.
- Product review remains for explicit English-language reversal, direct incoming qualification/booking, calendar agent-filter windows and English vendor SDK errors. New product policy was not invented during QA.
- Coverage measures scoped statements/branches, not correctness or perfection. Raw missing lines/arcs and limitations are in [coverage-summary.md](coverage-summary.md).

No release approval or deployment is inferred from this report. Review the concrete QA patch and evidence, then satisfy the remaining gates.
'''
(reports/'release-readiness.md').write_text(text);print(f'Release report: {passing}/{len(gates)} local boundaries pass; verdict NOT READY')
