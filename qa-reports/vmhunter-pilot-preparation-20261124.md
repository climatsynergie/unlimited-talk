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

## NOT TESTED / pending

- User credential entry and provider authentication.
- Media stream conversion and integration, classification and call routing.
- Failure recovery and real-call acceptance with agents.
- Campaign and pilot agent selection; customer-facing greeting.
- Provider audio-processing terms and training opt-out confirmation.

The pilot remains inactive. This report does not claim telephony readiness.
