# Unlimited Talks

Foundation for rebuilding Unlimited Talks with a modular Python API and a
separate PostgreSQL database. The business application is under development.

## Current scope

- FastAPI API with liveness and database readiness endpoints.
- PostgreSQL schema migrations using Alembic.
- Separate runtime and migration roles.
- Docker-based local development and a separate managed-database deployment.
- Non-root API, bounded connection pools and read-only container filesystems.
- Communications disabled. No provider credentials or customer data included.

Authentication, the business frontend, contacts, campaigns, the calendar and
telephony integrations are not implemented yet.

## Local development

Requires Python 3, Docker Engine, Docker Compose and permission to use Docker.

```sh
python3 scripts/bootstrap-secrets.py
docker compose build api
docker compose up -d --wait --wait-timeout 180
curl --fail http://127.0.0.1:8110/health/ready
```

API documentation is at `http://127.0.0.1:8110/docs`. This is API documentation,
not the agent interface. PostgreSQL is not published on a host port.

Secret files are generated locally and never committed. The local secret
directory is private. Use Docker Compose's normal local credential handling only
for development; deploy separate credentials on each managed environment.

## Verification

```sh
python3 tests/verify_foundation.py
python3 tests/verify_recovery.py
```

These scripts currently use passwordless `sudo -n docker` on the host. The
recovery test deliberately stops and restarts the local development database.
Do not run it against a shared or managed database.

GitHub Actions builds and tests an isolated environment using disposable
credentials. It does not access staging/production credentials or deploy to a
server. Continuous deployment will be configured separately after GitHub access
and staging deployment approvals are in place.

## Managed staging

`compose.managed.yaml` is an independent deployment file. Do not combine it with
`compose.yaml`, which starts a local database.

Set `STAGING_DB_HOST` and `STAGING_DB_CIDR` in the deployment environment, using
`.env.example` as a format reference. Replace example values with the private
database endpoint and network. Managed connections require TLS `verify-full`
and the provider's CA certificate. No environment-specific endpoints are stored
in this repository.

Provision separate database roles and the `staging` schema before migrating.
Provide the CA and role-specific secrets at the paths in the managed Compose
file. The runtime container must never receive database-administrator or
migration credentials. Local filesystem secret permissions must allow the
non-root container UID to read only its mounted credential.

The optional host egress service expects a root-controlled
`/etc/unlimited-talk-staging/network.env` containing `STAGING_DB_CIDR`. Review the
scripts before installing: they manage a dedicated Docker subnet and require a
dedicated staging host. Docker publication rules can bypass UFW; retain
loopback-only bindings until HTTPS and access control are configured.

## Data and secrets

Never commit database dumps, customer files, recordings, private keys,
certificates, passwords, tokens or deployment environment files. Operational
reports and legacy application data are not part of this repository.
