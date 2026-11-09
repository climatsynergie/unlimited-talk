# Release readiness

**Verdict: NO-GO for production release.**

The audit repairs confirmed defects and provides executable evidence. Native dependency review and live carrier acceptance remain blocked. The clean Docker build and complete Foundation CI passed on the QA branch. Production data, routing and deployment were not changed.

## Reviewed source and environment

- Baseline: main/deployed `662b450501a70431b0effbb087501e727111099d`; incoming candidate `96f5055b7fff29257a0e306e0658721394cc80a7`.
- Isolated branch: `qa/full-audit-20261108`. Exact application/image hashes: [source manifest](evidence/final-source-manifest.json).
- Tests use isolated PostgreSQL, Redis, an S3-compatible mock and synthetic Twilio fixtures with external communications disabled.
- Observed production was on schema11. Candidate schema12 still requires a controlled release; this audit does not activate incoming routing on the existing server.

## Validation

Accepted local boundaries: **23/23 PASS**. This is a gate count, not percentage completion. See [regression-results.md](regression-results.md) for the commands, exits and original failures.

All selected local boundary gates pass after repair. Original failed attempts remain preserved.

Seven high application findings, five medium application findings and two low findings were repaired in the QA branch. The low findings concern documentation and reception-panel spacing. One additional high dependency release gate remains open. Conditional Critical vendor advisories are not represented as proven Critical application exploits. See [findings.md](findings.md).

## Required before release

1. **Resolve native image advisories.** Test patched/re-pinned images and rescan, or support each remaining issue with a narrowly justified VEX review. The gateway's latest tag resolves to the same affected digest, so pulling again alone cannot resolve this gate.
2. **Use the reviewed release process after approval.** Foundation CI passed on QA code commit `e09d9e496440d333a6433c595b2bf6d46cc66e85`: [run42537634865](https://github.com/climatsynergie/unlimited-talk/actions/runs/42537634865). This includes a clean Docker build. The earlier local build failure remains preserved. The publish job was skipped; no release image was published, no merge occurred and no deployment ran. A later approved main release must verify its own digest/revision/attestation.
3. **Complete carrier acceptance.** On a selected UT-only line, test real inbound/outbound calls, two-way headset audio, recording/archive/playback and missed-call/voicemail behavior. Progress from three to twenty real agents with measured latency/CPS and occupancy checks. Local synthetic admission and real browser/API/PostgreSQL flows already pass their stated scopes.
4. **Review credentials and cloud access.** Confirm previously exposed credentials were rotated/revoked. Verify line ownership/routing, Spaces permissions, trusted sources, IAM and monitoring. Live secret values are excluded from reports; retained traces can contain disposable synthetic credentials.
5. **Review complete-system recovery.** Verify managed PostgreSQL PITR/failover, object-storage restore/retention, host restore and secret/MFA-key recovery. Local database restore/outage tests do not establish full production disaster recovery.

## Residual limits

- Real PSTN quality, provider retry timing and hardware permissions remain **BLOCKED**.
- The parser passed the advertised 100,000-row / exact10-MiB bound within512MiB. Full PostgreSQL import throughput and mixed20-agent workload were **NOT TESTED**.
- Every endpoint/input permutation, browser/screen-reader/device combination, distributed slow-trickle attack and navigation/lost-ack combination was **NOT TESTED**.
- Product review remains for explicit English-language reversal, direct incoming qualification/booking, calendar agent-filter windows and English vendor SDK errors. New product policy was not invented during QA.
- Coverage measures scoped statements/branches, not correctness or perfection. Raw missing lines/arcs and limitations are in [coverage-summary.md](coverage-summary.md).

The code is pushed only to the QA branch. Raw forensic evidence remains local because repository push protection rejects generated synthetic Twilio identifiers; no bypass was used. Public API download of CI logs returned403, while run/job/step success metadata is preserved. GitHub conclusions do not expose process exit codes; local commands retain actual exits.

No release approval or deployment is inferred from this report. Review the concrete QA patch and evidence, then satisfy the remaining gates.

Final report updates are retained in the isolated worktree. The pushed and CI-tested software commit is e09d9e496440d333a6433c595b2bf6d46cc66e85; subsequent changes affect QA documentation/tools only. Raw forensic files and screenshots remain local.
