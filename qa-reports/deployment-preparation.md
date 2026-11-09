# Controlled deployment preparation — 9 November 2026

Status: **PREPARED; NOT DEPLOYED**. The user now authorizes deploying fixes. Their earlier explicit instruction not to merge main has not yet been revoked; clarification for that separate main promotion is pending.

Candidate: `405dc5a611da7795ecac85b7302c54702502e9b8`. [Review exact source delta](https://github.com/climatsynergie/unlimited-talk/compare/main...qa/full-audit-20261108). [Successful functional CI](https://github.com/climatsynergie/unlimited-talk/actions/runs/42685739475). Security and real-carrier residuals remain as documented in [readiness](native-refresh-readiness.md); this preparation does not turn that audit into a production certification.

Read-only server health confirmed current release662b450, schema11, manual calling enabled. The latest corrected read-only activity check found0 active outgoing calls and0 live running dialers. The first activity query used the wrong column (`state` instead of `mode`), failed in a read-only transaction and was corrected; no rows were modified. Activity must be checked again immediately before deployment.

Installed deployer, call-control, gateway-preparation, line-connection and boot-resume operator hashes match the reviewed versions. The current application's compatibility labels permit rollback after additive schema12 without a data downgrade.

The new managed Compose and Nginx templates were staged under a private root-owned candidate directory, not installed over active templates. Compose validation exited0. Both official selected gateway/broker images were cached by immutable digest; image pulls exited0. A network-disabled, read-only, resource-limited Nginx container validated the candidate config with exit0 and no port/data mount. Exact commands/output and script hash are retained in `evidence/release-preparation/stage-candidate.json` and its log.

Remaining controlled sequence:

1. Obtain explicit main-promotion clarification, preserving the earlier no-merge instruction until answered. No force push or deployment-provenance bypass.
2. Promote the reviewed candidate via the approved repository path; require successful main-branch Foundation CI, image publication and attestation. QA-branch success did not publish a deployable image.
3. Complete server backup/restore-point checks, install backed-up reviewed templates, validate/pull immutable dependencies, and recheck live-call activity. Host pg_dump is not installed; a compatible reviewed client is needed for a new private database snapshot if managed recovery evidence is unavailable. Do not print customer data or credentials.
4. Run the restricted deployment workflow for the exact current main SHA. Neither local nor server GitHub CLI has an authenticated Actions identity. A GitHub connection has been suggested; it is not confirmed installed. A manual authorized workflow dispatch remains an alternative if no API identity is available.
5. Verify exact live revision/schema/health, preserved calling mode, worker health, endpoint access controls and static UI. No real call or Twilio route rewrite is authorized by this preparation. Connecting an incoming line remains a separate controlled provider action.

The running application, current release pointer, active templates, customer rows and calling mode were not changed. No main merge or real call occurred.
