# Seventeen-agent readiness assessment — 16 November 2026

## Decision

**Application admission: PASS for 20 synthetic simultaneous agents. Real 17-agent telephony/media acceptance: NOT TESTED.** A controlled rollout is appropriate; an unconditional promise of 17 real conversations is unsupported. No real calls were initiated.

## Live read-only observation

At 01:15:34 UTC, release 553c0bb was READY, database connected at 0012, manual calling enabled. The shared inbound/outbound application ceiling was 20 calls and the effective manual duration was 1800 seconds. Host RAM 7941 MiB, available 6848 MiB ; 137 GB approximately of disk free. Seven services were running; six configured healthchecks healthy, worker has no healthcheck; no observed OOM. Zero active calls at the instant measured. These are idle observations, not peak-load proof.

**PASS, exit 0:**

```sh
ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 /root/qa-read-capacity-20261116.py
```

[Exact metadata](evidence/capacity20-live-readonly.json), [output](evidence/capacity20-live-readonly.log). The probe reads profile/public health/SQL in a READ ONLY transaction and prints only capacity/aggregate health. It performs no carrier API operation.

## Isolated HTTP/PostgreSQL experiment

**PASS, exit 0, 19.397 s full experiment.** Source revision 0e18ba6. The existing voice HTTP/PG regression harness was copied into the evidence folder; only its three-agent block was expanded to 20 and given timing/evidence prints. This is an experiment, not a newly committed CI regression. Its existing environment guards require local DB hostname, disabled communications, and the database synthetic-only sentinel. The real application API and PostgreSQL execute inside a disposable Docker project with synthetic Twilio profiles/signatures; no credentials or real provider requests are used.

Verified:

- 20 independently authenticated agents concurrently reserved 20 distinct destinations; all accepted within 0.88 s wall time for the batch on this local machine. This does not establish a production latency SLA.
- 21st agent reservation rejected with 409 while the 20 slots were occupied.
- All 20 synthetic signed calls reached answered state together in the administrator API. Signed events were delivered sequentially; this does not simulate 20 audio streams.
-Each generated Dial used 1800 seconds. Every call finished, and each agent retained the correct recording ownership.
-The surrounding existing voice harness also completed its opt-out, revocation, destination, privacy, replay and recovery assertions.

```sh
env 'FOUNDATION_COMPOSE_ARGS=-p ut-capacity20-20261116 -f /home/codexdev/unlimited-talk-qa-audit/compose.yaml -f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/flexible-qualification-20261116/compose.qa.yaml' python3 qa-reports/evidence/capacity20-20261116/run.py
```

[Exact metadata](evidence/capacity20-http-postgres.json), [output](evidence/capacity20-http-postgres.log), [experiment sources/hashes](evidence/capacity20-20261116/source-hashes.json). Isolated database startup/migration/API/cleanup commands and exits are in `evidence/capacity20-lab-{start,migrate,api,cleanup}.json`; all exited0. Docker volumes were removed only for this synthetic project.

## Remaining acceptance

**NOT TESTED:** 17 real simultaneous PSTN/headset conversations, 17 browser/SDK sessions under sustained work, carrier concurrency/account limits, actual audio quality under the agents’ networks, long-running mixed incoming/outgoing load with bookings and imports. The experiment is not a benchmark of managed PostgreSQL or the live network.

For tomorrow, start with 5 agents, then 10, then 17; at each stage confirm two-way sound, calls continue after no-answer, correct contact/RDV, and no unexplained pauses. Observe errors, DB latency, occupancy and media quality before increasing. The ceiling 20 is shared by incoming and outgoing calls. No resource upgrade is justified solely by current idle RAM. See the existing [real-call acceptance plan](real-call-acceptance-plan.md) for carrier/headset steps, evidence and stop conditions. Real calls require owner authorization and human participants.

## Post-release confirmation

At01:33:26UTC, live revision0e18ba6 was READY with calling enabled, schema0012, shared maximum20 and effective duration1800seconds. Available RAM6814MiB; all seven services running, six configured checks healthy, no observed OOM. **PASS, exit0:** the same read-only command above was rerun; [exact metadata](evidence/capacity20-live-readonly-final.json), [output](evidence/capacity20-live-readonly-final.log). These observations preserve the same scope limits: no real17-agent audio acceptance has been performed.
