# Delivery and recovery

## Source to running application

The Foundation CI workflow tests the image, exports it as an artifact and
publishes the same image to GHCR in a separate job. Publication never rebuilds
the application. Image labels identify the source repository and complete Git
commit SHA. GitHub generates a signed provenance attestation; runner and server
verify its source commit, main ref and expected CI workflow, rejecting
self-hosted builders. Artifacts are retained for three days; this is not a backup policy.

The **Deploy staging** workflow is manual and runs only from `main`. Supply the
complete SHA of a successful main build. The workflow resolves the GHCR tag to
an immutable digest. The server independently checks current-main membership,
successful CI/publication, the allowed registry and the image's source labels.

Package publication uses GitHub's short-lived `GITHUB_TOKEN`. No personal access
token is required. If organization policy denies package creation/publication,
the owner must enable the intended package permissions; the pipeline must not
bypass a failed publication job.

## One-time GitHub configuration

Create the repository environment **staging** in Settings → Environments.
Restrict deployment branches to `main`. Required reviewers are optional for
staging; production must have its own separately controlled environment.
Environment feature availability depends on repository visibility and GitHub
plan; review protections before changing a public repository to private.

Add these three **environment secrets**, not source files or chat messages:

| Secret | Value |
| --- | --- |
| `STAGING_SSH_HOST` | Dedicated staging server's public SSH address |
| `STAGING_SSH_KEY` | Dedicated restricted CI private key |
| `STAGING_SSH_KNOWN_HOSTS` | Verified host key line using alias `staging-target` |

The administrator's console helper on the staging server prints one field at
a time for direct entry into GitHub Settings:

```sh
python3 /root/github-staging-setup.py host
python3 /root/github-staging-setup.py key-base64
python3 /root/github-staging-setup.py known-hosts
```

Never paste the private key into an issue, pull request, workflow log or chat.
The base64 output is still a private credential, not encryption. The workflow
decodes it locally, validates it with OpenSSH and prints only its public-key
fingerprint. Multiline OpenSSH secrets remain supported, including CRLF input.
Do not reuse the administrative SSH key. Rotate this restricted key if it is
exposed; remove/replace its authorized-key entry and GitHub environment secret.

The GitHub repository's write key and the staging server's CI deployment key are
different credentials. CI deployment needs no repository write permission.

## Server contract

An administrator installs `scripts/deploy_staging.py` as root-owned
`/usr/local/sbin/unlimited-talk-staging-deploy`, plus an audited managed Compose
and Nginx template under `/etc/unlimited-talk-staging/deployment-template/`.
The deployer does not download and execute host shell scripts from a commit.
Template changes are infrastructure changes, reviewed and installed separately.

The `stagingci` account has no Docker group membership and a locked password.
Its SSH key has `restrict` and a forced command. The sudo rule permits only the
installed deployer, without command-line arguments. Payload fields cannot
select a shell, path, database, registry or arbitrary image tag.

Persistent database credentials and TLS CA stay on the server. Registry
authentication uses the workflow's ephemeral token and a temporary Docker
configuration directory, deleted on exit. Docker image retrieval is a host
operation; the application container's restricted egress remains unchanged.

The root-controlled database profile and deployment-network JSON select the
private endpoint/network. A release gets a private `.env` containing endpoints
and the image digest, not database passwords. No database container is started.

## Deployment sequence

1. Lock deployments so simultaneous requests cannot overlap.
2. Validate the exact commit, successful CI and allowed digest.
3. Pull the immutable image and verify its commit/source labels.
4. Create a release directory with the audited server template.
5. Run migrations with the migration identity while the previous API remains.
6. Switch the current release, start API/gateway and wait for readiness.
7. Check that readiness reports the expected application commit.
8. Record the release and preceding release in a private operator state file.

Staging may have a short application interruption during container replacement.
No production deployment target is configured in this repository.

## Failure and rollback

Validation/pull/migration failure stops before switching the current release.
Application startup/readiness failure restores the preceding application image
and checks its health. No database downgrade, restore or deletion is performed.
This is safe only with the documented expand/contract migration policy:
schema changes must support the preceding application release. Destructive
cleanup requires a separate reviewed migration after the transition completes.

If application restoration also fails, the deployer reports failure and leaves
database data intact. Operators inspect service logs and repair forward.
Current deployment diagnostics:

```sh
systemctl status unlimited-talk-staging-managed
cd /srv/unlimited-talk-staging/current
docker compose -f compose.managed.yaml ps -a
docker compose -f compose.managed.yaml logs --tail 100 api gateway
cat /etc/unlimited-talk-staging/last-deployment.json
```

An active oneshot systemd unit does not prove that containers remain healthy;
monitor container health and endpoint readiness. Continuous alerting and backup
restore testing remain separate acceptance requirements before real workloads.

## Tests and remaining activation

CI tests request validation, rejected mutable images,
rejected non-main revisions and application rollback without schema downgrade.
The restricted server account must also reject interactive SSH commands.
Configuration and isolated database tests must remain green.

The first complete GitHub → registry → staging delivery is not considered
verified until the three environment secrets are configured and a real workflow
run succeeds. A prepared workflow or a unit test alone does not establish this.

## HTTPS access

The host Caddy service provides staging HTTPS and a password-protected perimeter.
See [the installation and verification contract](infrastructure/caddy/README.md).
This configuration and its credentials are independent of application releases.
The first restricted GitHub delivery has been verified on staging.

## Identity migration rollout prerequisite

Deploy the schema compatibility release before introducing `0002_identity`.
The original foundation image accepts only `0001_foundation` and cannot serve as
an operational rollback target after a new revision is recorded. The compatibility
release explicitly accepts both revisions while still checking the staging
marker. Unknown revisions remain unhealthy. This does not run or implement the
identity migration; its future changes must be additive and preserve the tables
used by this release.

The compatibility release was tested with a simulated additive table/revision.
Identity CI now migrates the actual schema, exercises real synthetic accounts,
switches to the exact preceding compatibility image, verifies preserved user
data and migration state, then restores the new application. The host deployer
refuses identity's first migration unless that compatible release is running.

Before deploying identity, install the reviewed managed Compose template and
root deployer, run `scripts/prepare-identity-host.py --origin <HTTPS-origin>` as
the staging administrator, and install the console launcher from
`scripts/bootstrap-staging-admin.py` at `/root/bootstrap-staging-admin.py`.
Provisioning preserves an existing encryption key and never displays it. These
are host preparation steps; they do not migrate PostgreSQL, switch the running
application or create a real account. Follow [IDENTITY.md](IDENTITY.md) for the
browser API, first-admin setup, encryption-key recovery and remaining UI scope.

## Contacts compatibility preparation

Before applying `0003_contacts`, deploy the explicitly compatible French web
release described in [CONTACTS.md](CONTACTS.md). This release adds no contacts
tables or import service. Its disposable compatibility probe verifies that
identity remains available across the planned additive revision and that unknown
revisions fail closed. Actual contacts migration, object storage and background
import acceptance remain separate activation checks.

## Contacts activation (schema 3)

Use `CONTACTS.md` for the import durability and isolation contract. The managed
root template now contains api/migrate/gateway plus broker/worker/dispatcher and
requires a schema-3 image. Install the reviewed deployer/template, nginx limits,
broker startup script and private Spaces egress rule together. The host helper
copies credentials into explicitly mounted file secrets; credentials stay out
of source, releases, GitHub Actions and container environment variables.
The existing compatible staging revision must be healthy before migration.
User-managed deployment remains through Deploy staging with successful Foundation
CI and the complete current main SHA. Do not deploy an untested local image or
run migrations manually to bypass that pipeline.

## Campaign activation (schema 4)

Deploy compatibility commit `911177b3181d849115fa5cedd00dd4a21cfcda60` first while
main still points to that commit. The campaign feature can be reviewed/tested on
its feature branch in parallel. Only after the compatibility predecessor is
actually healthy on managed staging should the feature be promoted to main.
Install the reviewed root deployer with the schema-4 compatibility gate; the
six-service Compose template, credentials and egress rules stay the same.
Publish the exact tested image with provenance, then use Deploy staging with its
complete current-main SHA. An application rollback keeps schema 4 and all data.

## Calendar compatibility preparation

Before introducing `0005_calendar`, deploy the schema-4 compatibility release
specified in [CALENDAR.md](CALENDAR.md). It adds no calendar tables or visible
calendar controls. Readiness admits schemas 4 and 5 while continuing to check all
existing campaign tables, the staging marker and identity encryption. CI verifies
the explicit planned revision and rejects unknown revisions in a disposable local
database. Verify its exact deployed SHA before promoting the calendar feature.

## Calendar activation (schema 5)

The required compatibility predecessor is
`0601ff555cc27e07057a499ac37ba349e399650e`, verified healthy on schema 4 before
calendar promotion. Install the reviewed root deployer with its schema-5 gate;
the six-service template and credentials remain unchanged. Record a private
predeployment data fingerprint, deploy the attested successful current main
image, and verify readiness at schema 5 plus preservation of existing records.
See [CALENDAR.md](CALENDAR.md) for behavior, permissions, DST handling and tests.

## Callback compatibility preparation

Before introducing `0006_callbacks`, deploy this schema-5 calendar compatibility
release. It explicitly accepts schema 5 and the planned additive schema 6, without
creating callbacks tables or activating reminders. Unknown/older revisions still
fail readiness. Record the exact verified healthy SHA as the required predecessor
in the reviewed deployer before permitting schema 6. Actual callback functionality
and its migration must be tested and promoted separately.

## Callback activation (schema 6)

Require healthy schema-5 compatibility revision
`5c626b006a3166f6bb308765938cd08bf2fda935` before promoting callbacks to main.
Install the reviewed deployer with its schema-6 predecessor gate; keep the existing
six-service template, secrets and networking. Record a private old-table snapshot,
deploy the successful attested main image, then verify exact readiness and source
data preservation. [CALLBACKS.md](CALLBACKS.md) defines ownership, reservations,
priority boundaries and the remaining authoritative phone-integration contract.

## Telephony proof preparation

`TELEPHONY.md` records the separate engine and controlled-call proof. The root-only
Twilio preflight tool checks one selected number using a restricted read key; it
cannot originate calls, modify routes or provision resources. It is installed
outside application containers and requires no app rollout. The queued contact
button spacing fix stays with the next substantive application delivery; do not
request a deployment for this layout correction alone.
