# Scheduled callbacks

Callbacks are durable business records in PostgreSQL, independent of Redis task
ETAs. Each records contact, source campaign, scheduling agent, UTC due instant,
IANA timezone, notes, status, version and immutable history. The owner is always
the authenticated creator; clients cannot forge or reassign ownership. Admins can
view/edit all callbacks, agents only their own. Existing ownership/history remains
readable after campaign unassignment; rescheduling requires active assignment.

## Scheduling and reservation

Create through a campaign contact's **Programmer un rappel** form. Creation
requires a currently assigned active campaign, active membership, current card
version, a future instant and a contact without global non-interest/suppression.
The shared scheduling resolver rejects nonexistent DST wall times and requires
an explicit UTC offset for repeated fall-back hours. The server independently
validates dates and zones. Rescheduling validates future instants; closing an
overdue callback is allowed without inventing a new future date.

There is one pending callback per canonical contact across all campaigns, enforced
by a partial unique index. It reserves the contact for its scheduling agent until
resolved. A second agent cannot schedule a competing reservation. Creation moves
the source campaign card to the semantic `callback` stage in the same transaction,
with both histories. A client UUID and exact normalized payload hash make creation
retries safe; stale card versions and conflicting UUID payloads fail with 409.

Statuses are `scheduled` (Programmé), `completed` (Traité) and `cancelled` (Annulé).
Every update locks the canonical contact before its callback and checks the
expected callback version. Conflicting edits return 409. Closed records cannot
be reopened silently: a new callback requires a new explicit scheduling action.
Marking a callback treated manually does not invent a call, attempt or disposition.
Closing a callback does not infer a campaign outcome or reverse a pipeline stage.
Changing a pipeline stage alone never invents a dated callback.

Global Non intéressé / Ne pas contacter cancels pending callbacks atomically with
the restriction. An actual appointment booking resolves its contact's pending
callback, also within the appointment transaction. Removing the contact from its
source campaign cancels that source reservation. All record before/after state,
actor, timestamp and reason. Reactivation never resurrects a cancelled callback.
Archival, owner deactivation or assignment revocation block priority processing;
the record remains visible for its owner/admin to resolve or cancel.

## Priority and future phone integration

`due_candidates` returns the requesting agent's due, pending, unblocked callbacks
ordered by due time then stable UUID. It excludes restricted contacts, inactive
owners, archived/unassigned campaigns and removed memberships. A campaign switch
must not transfer callback ownership or limit callbacks to the selected campaign.
List views show due reminders first; history shows recent due dates first.

The priority endpoint is **read only**. It does not claim a contact, start a call,
create a result, or infer that an agent is available. Telephony remains disabled.
No callback reminder exists only in an in-memory timer or delayed Celery message:
a restart or broker outage does not erase the schedule, and overdue records remain
queryable after recovery. Read polling uses authentication without touching session
activity, preserving idle expiry.

When integrating the phone engine, the authoritative agent controller must:

1. Respect pause/stop and in-call/appointment-entry states before claiming work.
2. Prefer that agent's due callbacks over ordinary campaign contacts, with the
   callback's original campaign and caller-ID policy.
3. Atomically claim/lock the canonical contact and recheck the callback version,
   status, due time, ownership, active assignment and all global restrictions.
4. Enforce campaign calling hours, the global two-attempts-per-local-day maximum
   and two-hour minimum spacing. Being due does not override those limits.
5. Exclude every pending callback's contact from ordinary campaign queues, even
   in other campaigns. A readonly candidate list alone never provides call locking.
6. Finish/reschedule the callback using the actual call ID and validated outcome,
   with idempotent provider event handling. Do not mark a reminder completed merely
   because it appeared in a list or a provider API request was sent.

Agent availability, call claims, provider events, call attempts and automatic
origination belong to the upcoming phone integration, not this scheduling module.
This is not a capacity test or a claim that calling is operational.

## API and interface

Existing session, exact-origin and CSRF protections apply:

- `GET /api/scheduling/resolve`: shared local-time resolution. The calendar's old
  `/api/calendar/resolve` URL remains a compatible alias.
- `GET /api/callbacks`: scopes `upcoming`, `due`, `history`, `all`, optional owner
  filter (agents cannot request others), 100 rows/page and explicit `has_more`.
- `GET /api/callbacks/priority`: at most 20 readonly due candidates for this user.
- `POST /api/callbacks`: UUID, campaign/contact IDs, current membership version,
  local start, timezone, optional offset minutes and notes up to 5000 characters.
- `GET /api/callbacks/{id}`: owned/admin detail with paged immutable history.
- `PATCH /api/callbacks/{id}`: schedule, status, notes and expected version.

The French **Rappels** page provides pending, due and historical lists, ownership
and blocking reasons, explicit pagination, refresh and 30-second visible polling.
Only the callback owner or an administrator can open its detail. Forms retain
input after errors and close only after a successful save or explicit cancellation
of entry. Desktop/mobile layouts use the existing theme and accessible controls.

## Rollout

Migration `0006_callbacks` adds `callbacks` and append-only `callback_events`.
Indexes support per-agent/global pending priority, chronological lists and history.
The runtime role cannot delete/truncate callbacks or rewrite/delete/truncate their
history. Application rollback preserves the schema and all records.

Prerequisite: deploy calendar compatibility revision
`5c626b006a3166f6bb308765938cd08bf2fda935` and verify actual healthy schema 5 before
promoting the callback feature to main. The reviewed host deployer requires that
exact predecessor or an already healthy schema-6 release. Container templates,
networking, identities, secrets and workers do not need new privileges or services.
Record a private pre-migration fingerprint and use the existing attested deployment
workflow. Do not apply managed migrations or hotpatch application containers manually.

Disposable tests cover populated schema upgrades, ownership and campaign guards,
retry safety, competing callbacks, version races, due ordering, suppression,
appointment/removal cancellation, immutable history, browser save recovery,
rescheduling and closure, actual predecessor rollback, backup/restore and outage
recovery. Managed verification and user acceptance follow the real deployment.
