# CVC MTL VM Hunter activation — 25 November 2026

Owner requested VM Hunter on CVC MTL for every assigned agent, preserving CHIN LIST 514_REGION. At 19:18 UTC read-only production inspection found zero nonterminal outbound calls; most dialers paused, two old running leases expired. No agent was paused by this change.

## Scope and design

Version 4 policy contains an explicit campaign UUID list: CHIN LIST 514_REGION and CVC MTL. Versions 1–3 remain compatible. All active assigned users/current canonical contacts are checked live for each campaign; no wildcard, manual-call expansion, stale agent snapshot or Twilio number route change. Shared account concurrency and cleanup safety cover both campaigns. The existing pilot's identifier and total 500-claim budget are preserved; maximum two concurrent analyses remains. Above capacity or on failure, ordinary calling continues without filtering. This is not a 17-agent load/capacity certification or unlimited provider subscription.

No schema migration is required (schema remains 0012). The API must be deployed through the normal CI/provenance/idle-call protected workflow to read the new policy; a worker-only update cannot change the old API's hardcoded CHIN-only boundary. The worker must include the updated policy module as well as the observer. The optional operator installs only the already attested worker policy after the compatible API is live; it never changes Twilio routes, creates a call, restarts the API or changes calling mode.

## Executed local verification

Exact commands, source hashes, actual exits and raw logs are in each evidence JSON/log pair.

- **PASS:** full backend suite, 316 tests, exit 0: `evidence/vmhunter-multicampaign-backend-20261125.{json,log}`. Actual command is the recorded network-disabled Docker `python -m unittest discover -s /tests -p test_*.py -v`.
- **PASS:** host deployment/configuration tests, 36 tests, exit 0: `python3 -m unittest discover -s tests/host -p test_*.py -v`, `evidence/vmhunter-cvc-release-host-complete-20261125.{json,log}`. Tests deny stale-main, foreign/PR/failed CI, unauthorized policy scope and budget reset.
- **FAIL, initial synthetic fixture:** `evidence/vmhunter-multicampaign-postgres-20261125.{json,log}`, exit 1, duplicate active actor violated the existing `voice_one_active_actor` index. No production change or assertion was relaxed.
- **PASS:** corrected the fixture to finish a synthetic actor's call before creating another. New multi-campaign PostgreSQL proof, exit 0: `evidence/vmhunter-multicampaign-postgres-valid-actor-lifecycle-20261125.{json,log}`. Proves explicit campaign membership, all assigned agents, revoked assignment denial, shared two-job capacity, shared total budget (including removed campaigns), cross-campaign cleanup circuit and verified recovery.
- **PASS:** existing signed HTTP/WebSocket/PostgreSQL screening proof, 24 simulated analyses, zero real calls, exit 0: `evidence/vmhunter-multicampaign-surrounding-screen-20261125.{json,log}`.
- **PASS:** existing lease/budget/rollback-safe store proof, exit 0: `evidence/vmhunter-multicampaign-legacy-store-20261125.{json,log}`.

The three PostgreSQL proofs ran via `env FOUNDATION_COMPOSE_ARGS='-f /home/codexdev/unlimited-talk-vmhunter-release/qa-reports/evidence/vmhunter-release-20261125/compose.json' VMHUNTER_USE_LOCAL_SOURCE=1 python3 tests/verify_vmhunter_screen.py`, with no argument, `vmhunter-integration.py`, or `vmhunter-multicampaign-integration.py` respectively. All use disposable data and networks.

## Controlled deployment request

The owner-authorized request manifest triggers a narrow workflow only when that specific manifest changes on main. It validates the exact two campaign IDs and explicit deployment intent, waits for successful exact-source push Foundation CI, refuses changed main/failed CI, then dispatches the existing Deploy staging workflow. It receives no SSH secret and cannot bypass the installed deployer or idle-call guard. Other pushes are not automatically deployed by this request workflow. Local/server GitHub CLI tokens are unavailable; GitHub's own scoped Actions token can perform workflow_dispatch without exposing secrets. Host tests execute the request decision logic with no network or deployments.

**Pending:** immutable image CI, provenance, actual API/worker deployment, live policy activation and CVC call acceptance. Preparation is not activation. No real phone call is originated by tooling. Overall production certification remains NO-GO; inherited native security findings and real 17–20-agent filtering capacity are separate unresolved limitations.

## Deployment identity review

The requested release is dispatched with GitHub's scoped Actions token, whose actor can be `github-actions[bot]`. The existing root deployer intentionally accepts only a bounded registry login name, so passing that bot actor as registry_user would fail validation. The normal deployment and worker publication workflows now use the fixed repository owner as the GHCR login, preserving all existing CI/provenance/idle-call controls and token permissions. This prevents the actor-name incompatibility without relaxing the root deployer. The explicit release request was regenerated for the corrected source; the previous waiting request stops when main changes. No live API deployment or campaign enablement has occurred yet.

The owner confirmed the VM Hunter Free plan. No subscription upgrade is authorized for this rollout. Current internal limits are preserved: 500 shared total claims for this pilot and two concurrent analyses. Provider quota exhaustion or excess concurrency leaves ordinary calls available without filtering. The Free plan's published 5,000-call monthly allowance is a provider limit, not proof of remaining allowance in this account; see https://vmhunter.com/pricing.
