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
- Twilio Programmable Voice is the selected communications provider: browser
  media through the Voice SDK, call control through the backend. PostgreSQL
  remains authoritative for eligibility, intent reservations and agent state.
- No VICIdial/Asterisk host is required for this selected path. The previous
  SIP/image exploration remains historical evidence, not a provisioning plan.
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
- Admins explicitly assign which agents receive inbound calls. Unanswered
  inbound calls create durable follow-up in an Appels entrants pipeline, linked
  to the call history and any voicemail. Follow-up calls remain manual. See the
  inbound operating contract below for confirmed requirements and pending choices.
- Agent-to-agent hold/transfer and appointment confirmation automation remain
  outside the agreed initial scope. A bounded incoming waiting queue is a
  proposed extension, not an enabled feature.

## Inbound operating contract — scope added 31 October 2026

This records the requested behavior and implementation boundaries; inbound
routing and its pipeline automation are not implemented or activated yet.

Confirmed requirements:

- Admins select the agents allowed to receive incoming calls. Assignment is
  explicit and independent of the agent's currently selected outbound campaign.
- Calls not answered by an agent must be persisted and visible in a pipeline
  provisionally named Appels entrants. An incoming call must not disappear when
  its caller disconnects, the browser closes or a notification arrives late.
- Preserve the contact when identifiable, the called business number, arrival
  time, routing/offers, answering agent when applicable, outcome and any voicemail
  or recording metadata. Existing contact/campaign history is retained.
- Missed-call follow-up remains manual, as previously agreed. A missed incoming
  call does not automatically enter the outbound campaign dialer.

Recommended operating model accepted on 31 October; numerical settings and
opening hours remain configurable implementation choices:

- Configure inbound queues by business number, with assigned agents, hours and
  timezone. Do not silently attach all numbers to one campaign or change legacy
  number routing. Existing number ownership must be verified before activation.
- Agent states distinguish offline, ready, reserved/ringing, in conversation,
  optional after-call work, appointment form, pause and stopped. An online browser alone
  never establishes readiness. Expired presence stops new offers without freeing
  an established call whose provider outcome remains uncertain.
- Preserve the agreed automatic outbound continuation: do not impose a new
  mandatory wrap-up delay after every call. The appointment form and explicit
  pause/stop keep their existing precedence.
- Reserve one eligible agent atomically across incoming and outgoing work.
  Never interrupt an established conversation or offer a second call to a busy
  agent. Inbound-only, outbound-only and mixed permissions are admin settings;
  mixed agents give waiting inbound calls priority over starting fresh outbound
  calls. An established conversation is never interrupted. Due agent-owned
  callbacks retain their explicit ownership; do not assign them to another agent.
- Offer to the longest-idle eligible agent, then try another on rejection or
  timeout. An individual missed offer is distinct from a caller who never
  reaches any agent. Queue wait and offer limits must be configurable and bounded.
- Use a French waiting announcement, then voicemail if no agent answers.
  Also record abandonment before answer and arrivals outside opening hours.
  The initial policy defaults are a 60-second queue wait, 20-second offers bounded
  by the remaining wait, and a 30-second presence freshness limit. Expiry of an
  offer requires confirmed provider completion before another offer; elapsed
  time alone never frees an agent or authorizes a duplicate call.
- Follow-up stages: À traiter, Pris en charge, Rappel programmé,
  Traité. Voicemail presence and telecom outcomes (missed, abandoned, answered)
  are separate facts, not substitutes for follow-up status. A booked appointment
  links the actual calendar entry rather than fabricating an appointment outcome.

Implementation boundaries:

- Separate the live media queue, immutable call events and the CRM follow-up
  pipeline. Moving a card must never answer, hang up or originate a call.
- Existing campaign cards are unique per contact/campaign. Do not force repeated
  incoming calls into that single record as though it were an individual call.
  Persist every call separately; group open follow-up for a contact/queue with
  links to each interaction. An anonymous caller still needs an interaction,
  without inventing a phone number or merging unrelated anonymous callers.
- Claim ownership of shared follow-up atomically so two agents cannot unknowingly
  return the same call. Repeated provider events cannot duplicate calls, cards,
  ownership changes or callback schedules. A new missed call after closure opens
  follow-up again without rewriting the previous history.
- An incoming contact match does not remove global outbound restrictions.
  Return calls still recheck contact eligibility and agent authorization.
- PostgreSQL remains authoritative for business state. Twilio can provide media
  queues and agent routing; if TaskRouter is selected, its reservations must be
  reconciled with application claims, never become an independent second owner.
- Reports distinguish offered, agent-answered, abandoned and overflowed calls,
  queue wait, agent response time and unresolved follow-up age. A voicemail or
  waiting greeting is not an agent-answered conversation.

Before activation, verify simultaneous inbound/outbound claims, stale presence,
offer timeout/rejection, caller abandonment during an offer, duplicate and late
events, lost callbacks, multiple calls from one contact, private voicemail access
and restart recovery. The existing controlled outbound test stays disabled until
its separate integration checks pass; this scope adds no provider routing change.

The decision component `backend/app/telephony/inbound.py` is now prepared and
scenario-tested for assigned/available agents, longest-idle ordering, bounded
offers, verified rejection, uncertain outcomes, overflow and caller abandonment.
It is deliberately a policy proposal over trusted snapshots, with no provider or
database effects. Durable queue/agent reservations, follow-up persistence, admin
settings and the browser receiving flow still need their implementation and
integration proof before incoming call handling can be considered delivered.

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

Currently verified on managed staging: isolated infrastructure, private managed
PostgreSQL, HTTPS perimeter, individual accounts/MFA, French React interface,
private CSV imports, canonical contacts, configurable campaigns/pipelines, shared
notes, the shared calendar and durable agent-owned callbacks. See IDENTITY.md,
WEB.md, CONTACTS.md, CAMPAIGNS.md, CALENDAR.md and CALLBACKS.md for their contracts.
Calls, SMS and recordings are not activated. TELEPHONY.md defines the controlled
integration proof and the responsibilities that must precede live origination.

## Shared calendar implementation

Appointments owns a shared Unlimited Talks calendar with UTC instants plus IANA
timezones, creator/admin editing and immutable change history. Booking calls the
campaign domain inside the same database transaction to classify the contact as
RDV booké. It does not couple appointment state to a telecom or external calendar
provider. Multiple meetings may overlap; cancellation preserves both histories.
See [CALENDAR.md](CALENDAR.md) for the contract and rollout prerequisite.

## Durable callback scheduling

Callbacks owns dated agent reservations and immutable history in PostgreSQL, not
broker ETA timers. Campaign suppression, source membership removal and real
appointment booking cancel matching reservations in the same transaction. A shared
timezone resolver serves both calendar and callback entry. The communications module will
own availability, atomic call claims and attempt limits; callback priority queries
are readonly candidates and cannot originate calls. See [CALLBACKS.md](CALLBACKS.md).
