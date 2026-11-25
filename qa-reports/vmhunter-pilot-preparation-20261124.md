# VM Hunter credential preparation — 2026-11-24

Scope: offline operator credential entry only. Application code, Twilio routing,
campaigns and running services are unchanged. No provider authentication request,
audio transfer, analysis or real call is authorized or performed by this helper.

## PASS — local credential security tests

Executed command:

```sh
python3 qa-reports/tools/run_check.py vmhunter-credential-tests-20261124 -- python3 -m unittest discover -s tests -p test_vmhunter_credentials.py -v
```

Exit 0; 11 tests. Evidence: `qa-reports/evidence/vmhunter-credential-tests-20261124.{json,log}`.
Final committed-source verification uses the same unittest command with evidence
label `vmhunter-credential-final-20261124`.

Coverage includes masked entry, mismatch rejection, root-only CLI, private file
permissions, symlinks/hardlinks/FIFO rejection, bounded reads, interrupted writes,
no overwrite, redacted failures and prohibited network access during entry.

Helper: `scripts/store_vmhunter_credentials.py`; server destination:
`/root/store-vmhunter-credentials.py` (root-owned, mode 0600).
Credential destination: `/etc/unlimited-talk-staging/vmhunter-credentials.json`
(root-owned, mode 0600). Credentials are not committed to Git.

## PASS — standalone helper installation

Executed command:

```sh
python3 qa-reports/tools/run_check.py vmhunter-helper-install-20261124 -- python3 qa-reports/evidence/install_vmhunter_helper_20261124.py
```

Exit 0. Source verification: `b185ad7d147083ae4df251e9b465bdae9c89caa5`;
helper SHA256 `e098085c3f934f267c6c935d50483430a16ad0a522ba095691e5ca60fffb4d48`.
Remote file verified root-owned, regular, single-link and mode 0600; `--help`
executed successfully. Readiness returned HTTP 200 before/after installation,
both `ready`, revision `c93d2d113962ee3875940c0f9f403b5b4c82c0c3`,
calling enabled, migration `0012_incoming_runtime`. Current release unchanged.
Evidence: `qa-reports/evidence/vmhunter-helper-install-20261124.{json,log}`
and installer source in the same evidence directory. Final committed-source
tests: exit 0, 11 tests (`vmhunter-credential-final-20261124.{json,log}`).

## PASS — user credential entry and campaign identity

User reported completing entry. Executed root-server command:

```sh
python3 /root/store-vmhunter-credentials.py status
```

Exit 0: stored configuration and file protections validated without displaying
the key. This does not authenticate the key with the provider.

User selected “chin list 514 region”; confirmed exact campaign:
`CHIN LIST 514_REGION`, UUID `2bdf5195-0b52-49b1-aecc-0caaf5459e77`.
It is active, uses `America/Toronto`, has 9 active assigned agents and its existing
automatic dialer is enabled. No campaign settings or assignments were changed.

Executed command:

```sh
python3 qa-reports/tools/run_check.py vmhunter-campaign-inspection-20261124 -- python3 qa-reports/evidence/vmhunter_campaign_inspect_20261124.py
```

Exit 0. PostgreSQL `SHOW transaction_read_only` returned `on`; bounded,
parameterized inspection with 3-second statement timeout. Evidence:
`qa-reports/evidence/vmhunter-campaign-inspection-20261124.{json,log}` and
inspection script in that directory.

Pilot design must select BOTH this immutable campaign ID and explicitly chosen
pilot agent IDs, never all 9 campaign members by default. Agent choices remain
pending. Manual calls, other campaigns and inbound reception remain out of scope.
The existing outgoing call generator is agent-first `Dial/Number` with dual
recording, child-leg status callbacks and a dial-finish callback. Screening before
agent connection needs a separately tested flow preserving those contracts.
No media bridge or filtering code has been installed or enabled.

## NOT TESTED / pending

- Provider authentication.
- Media stream conversion and integration, classification and call routing.
- Failure recovery and real-call acceptance with agents.
- Pilot agent selection and customer-facing greeting.
- Provider audio-processing terms and training opt-out confirmation.

The pilot remains inactive. This report does not claim telephony readiness.

## Subsequent implementation

The isolated observation integration and regression evidence are documented in
`qa-reports/vmhunter-observation-20261124.md` and
`deployment/vmhunter/README.md`. The company name supplied is Maisonverte Québec.
The candidate has not been deployed; automatic voicemail suppression and the
pre-agent announcement have not been enabled or implemented by this preparation.
