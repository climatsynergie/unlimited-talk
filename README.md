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

Individual authentication and the React account/admin interface are implemented.
Private contact imports, campaigns/pipelines, the shared calendar and agent-owned
callbacks are implemented. A controlled Voice API and its additive migration are
prepared on the telephony branch; live communications remain
disabled. See [TELEPHONY.md](TELEPHONY.md) for the current Twilio integration boundary.

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
credentials. Successful main builds publish the exact tested image to GHCR.
Tests never receive staging/production credentials. The separate **Deploy
staging** workflow requires the staging environment's restricted SSH settings
and an explicit request for a successful current-main commit.

See [ARCHITECTURE.md](ARCHITECTURE.md) for system boundaries and the agreed
business invariants, and [DELIVERY.md](DELIVERY.md) for deployment and recovery.

## Managed staging

`compose.managed.yaml` is an independent deployment file. Do not combine it with
`compose.yaml`, which starts a local database.

Set `STAGING_IMAGE`, `STAGING_DB_HOST`, `STAGING_DB_CIDR` and `STAGING_APP_ORIGIN` in the deployment environment, using
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

## Identity backend

See [IDENTITY.md](IDENTITY.md) for the individual account API, admin MFA,
invitation/session contract, operational bootstrap and activation boundaries.
See [WEB.md](WEB.md) for the React screens, browser verification and first login.
Automatic invitation email delivery is not implemented; admins share private links.

## Contacts preparation

The [contacts import contract](CONTACTS.md) records the implemented pure CSV
validator, the required private object storage/background processing, and the
activation boundary. No contacts/import endpoint is active yet.
