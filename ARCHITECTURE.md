# Architecture and delivery contract

This document records the target and current delivery boundaries. A service is
not considered delivered merely because its configuration exists: its complete
flow must pass verification in the intended environment.

## Target

- One modular application: React/TypeScript frontend, FastAPI backend.
- PostgreSQL is the durable authority for contacts, permissions, appointments,
  interactions, callback schedules and global call eligibility.
- Dedicated workers process imports and integrations. Redis/Celery will carry
  asynchronous work; a broker outage must not erase durable business state.
- Private object storage holds original imports and recordings, separate from
  database metadata. Retention and backup restore are explicit requirements.
- A separate VICIdial/Asterisk installation is the single dialing engine,
  subject to an integration proof. Its internal database remains separate.
- Twilio supplies numbers/telecom and messaging. No HighLevel dependency.
- Staging and production have separate credentials, databases and resources.
- Twenty simultaneous agents is an acceptance target to load-test, not a
  capacity claim based only on server RAM or agent account count.

## Modules and ownership

Identity owns users and roles. Contacts owns canonical phone identities and
imports. Campaigns owns membership, assigned agents and configurable pipelines.
Communications owns attempts, conversations, recordings and provider events.
Appointments owns the shared calendar and assignment history. Reporting reads
these durable events without inventing a second business source of truth.

Modules use explicit service/repository boundaries. Shared transactions are
allowed within the modular backend. Microservices are not a prerequisite.

## Agreed business invariants

- Admins import valid numbers; duplicate imports enrich one canonical contact
  without losing history. Contacts may belong to multiple campaigns.
- Admins assign campaigns. Agents may switch between assigned campaigns and
  move pipeline cards; mapped call outcomes also update stages automatically.
- Agents add shared, attributed notes but cannot edit contact coordinates.
- Non-interested is global across campaigns. Do-not-contact blocks calls and
  SMS globally and survives reimport. Automatic callers recheck these rules.
- At most two outbound attempts per contact per local day, globally across
  campaigns, at least two hours apart. Campaign schedules also apply.
- No-answer and machine attempts count and return to the queue tail when
  eligible. Machines are disconnected without leaving a message.
- Callbacks have a chosen date/time and belong to the scheduling agent. They
  wait for that agent and precede new campaign calls when due and eligible.
- Agents remain available unless paused/stopped. The appointment form reserves
  the agent until successful save or cancellation; pause/stop still wins.
- A missing agent disposition becomes Other and leaves automatic queues until
  manual reassignment. Late notes/dispositions must reference their original
  call ID, never whichever call happens to be displayed next.
- The shared Unlimited Talks calendar accepts simultaneous appointments.
  All agents see appointments; agents edit/cancel theirs, admins edit all and
  assign sellers later. Sellers have no accounts in the initial scope.
- All agents can read/reply to shared SMS threads, subject to global blocks.
  Recordings: agent accesses their calls; admins access all.
- Inbound calls go to an available agent; otherwise voicemail and a shared
  manual callback list. Hold/transfer and appointment confirmation automation
  are outside the agreed initial scope.

## Reliability boundaries

Eligibility checks and claims must be atomic across agents, workers and
campaigns. Use database constraints, explicit locking and idempotency keys.
Provider delivery is not exactly-once: duplicate/out-of-order webhooks and
uncertain provider outcomes require durable states and reconciliation.
Do not repeat an external call, booking or SMS blindly after a database retry.

Imports use validated jobs, bounded file sizes and durable progress. Calendar
writes and history commit together. A booking is shown as saved only after a
successful database commit. Caches do not authorize operations by themselves.

## Delivery

1. GitHub is the shared source of truth; commits use the owner's configured Git
   identity. Secrets and environment-specific operational reports stay outside.
2. Foundation CI tests HTTP, PostgreSQL permissions, outage recovery and
   configuration/deployment guards using disposable data and credentials.
3. CI exports the exact tested image. A separate, permission-scoped job verifies
   the archive and image identity, then publishes to GHCR without rebuilding.
4. Staging deployment is an explicit GitHub Actions workflow for successful
   current-main commits. GitHub environment protections can add approval rules.
5. The server accepts only the expected GHCR image by digest and checks its
   signed provenance, commit labels and successful CI. A forced SSH command replaces general shell
   access; the deploy key is separate from administrative SSH keys.
6. Credentials remain on the staging server. The short-lived GITHUB_TOKEN is
   used only to verify GitHub state and pull the image, with registry login in
   a temporary directory that is removed after use.
7. Migrations run using their own role before switching the application.
   Readiness verifies the actual database and deployed commit.
8. Application rollback can restore the previous image. It never reverses
   database writes or blindly downgrades schema. Migrations must follow an
   expand/contract policy compatible with the preceding application release.

## Definition of done

A milestone needs reproducible deployment, meaningful failure-path tests,
authorization checks, migrations, logs and a documented recovery procedure.
Public access additionally requires HTTPS and access control. Valuable data
requires backup restoration testing. Telephony requires real controlled audio
and provider tests; a mocked test cannot establish voice quality or capacity.

Currently delivered: staging foundation, private managed PostgreSQL, migrations,
isolated CI, attested image publication and verified restricted GitHub delivery.
Staging HTTPS uses a host Caddy service with a separate perimeter password.
The individual identity backend is implemented and tested as described in
IDENTITY.md; its managed staging activation is a separate deployment check.
Business modules and the React frontend are not implemented yet.
