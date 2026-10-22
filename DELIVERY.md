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
python3 /root/github-staging-setup.py key
python3 /root/github-staging-setup.py known-hosts
```

Never paste the private key into an issue, pull request, workflow log or chat.
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
