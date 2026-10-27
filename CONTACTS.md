# Contacts and private CSV imports

## Delivered flow

Administrators can open Contacts and Imports CSV. Agents cannot read the global
directory, imports, source files or contact history. Campaign-scoped agent access
will be added with campaigns; no implicit global permission is granted.

An administrator deposits a CSV through the same-origin, authenticated and
CSRF-protected API. The server streams at most 10 MiB into bounded memory and
stores the original as a private S3 object. It never writes source files to its
container filesystem. Filenames do not become storage paths. Credentials are
server file secrets, never browser credentials or presigned upload capabilities.

The administrator chooses UTF-8 or Windows-1252 and a detected/explicit separator,
associates columns, inspects row validation and explicitly confirms. Preview
changes no contacts. A confirmed mapping and staged row set become immutable.
The original SHA-256 must match when preview is generated; source replacement
through the API is refused after upload. Objects are written with a private ACL.

Limits: 10 MiB, 100,000 data records, 100 columns, 30 new imports per day across
staging. Only one preview is parsed concurrently. Each source column maps to at
most one profile field. A valid telephone is required; optional invalid fields
produce French warnings. Invalid telephone rows remain visible with row numbers.
No raw CSV content or contact values are written to application logs.

Telephone identities use phonenumbers/libphonenumber, default country CA and
canonical E.164. Extensions are rejected. Validation establishes structure,
not reachability or consent. Duplicates share one globally unique contact ID.
Incoming nonblank profile values enrich existing contacts. Blank cells never
erase existing values, and imports never change do-not-contact/non-interested
flags. Each applied valid row records the previous and incoming profile in
append-only history, visible from the Contacts screen.

## Durable execution

PostgreSQL owns source fingerprints, staged rows, explicit confirmation,
progress, counters and history. `next_publish_at` on a confirmed import is its
transactional outbox record. A separate dispatcher publishes only UUIDs into
an authenticated private Redis broker, then retries eligible jobs every 30
seconds until PostgreSQL says they completed. Lost publication or broker data
cannot erase accepted work. JSON is the only accepted Celery serializer;
there is no Redis result backend or contact payload in broker messages.

A single-concurrency Celery worker applies transactions of at most 100 rows,
locking the job with `FOR UPDATE SKIP LOCKED`. Contact merge, append-only history,
row outcome and counters commit together. A crash rolls back its incomplete
transaction; duplicate deliveries skip committed rows. Tasks run bounded loops
of chunks, and the dispatcher reconciles unfinished jobs. This deliberately
provides at-least-once delivery with idempotent application, without claiming
exactly-once transport. Pending imports remain visible if a dependency fails.

Worker and dispatcher cannot read S3 credentials or the identity encryption
key. The API cannot read the broker password. PostgreSQL pools are bounded to
2 per process; worker concurrency is 1. Redis has a 96 MiB no-eviction limit,
AOF persistence, bounded resources and no published port. Background import
polling validates sessions without refreshing their idle expiry. Contacts and
row lists are paginated and rendered as text, never HTML/formulas. No spreadsheet
export is introduced by this release.

## Deployment and recovery

The additive `0003_contacts` migration preserves all identity tables. The root
restricted deployer requires the already deployed compatibility predecessor
`423e16b69b5ffbb2f2d7fd4846e0f50f90eaef3e` before upgrading a schema-2 server.
It accepts only schema-3 images for its six-service template, verifies CI and
image provenance, migrates first, then switches the API and workers. A failed
activation stops new workers and restores the preceding application without
schema downgrade or contact deletion. Existing schema-3 workers are restored
when rolling back between schema-3 releases.

Install reviewed root deployment templates and `broker-start.sh`, provision
host secrets with `scripts/prepare-imports-host.py`, and configure only the
verified VPC Spaces gateway /32 on TCP 443 in the existing egress allowlist.
Never permit general Internet egress for these containers. Managed deployment
contains api, migrate, gateway, broker, worker and dispatcher; no database or
S3 emulator. Local/CI Compose adds disposable PostgreSQL and Moto S3 only.
Moto is a test fixture, never a production storage recommendation.

CI tests HTTP/database isolation, existing identity/browser behavior, private
import flow, crash rollback, duplicate delivery, broker publication/worker
execution, source fingerprint tampering, blank preservation, global contact
restrictions and session idle behavior. Actual predecessor image rollback
checks identity/contact fingerprints and import history/row counts. Synthetic
fixtures never use managed data. This is not a 20-agent telephony load test.

No source deletion schedule is enabled until its retention duration is chosen.
No automatic calls, SMS, campaign assignment or production migration is enabled.
