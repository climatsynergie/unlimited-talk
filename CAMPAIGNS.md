# Campaigns, pipelines and shared contact notes

## Scope and invariants

Campaigns organize globally unique contacts. One contact can have one active card
in each of several campaigns; no copying of contact identities or import history
occurs. Campaign/agent assignment, stage edits, card membership, notes and events
are PostgreSQL state. There is no telephone provider side effect in this module.

Administrators create/update/archive campaigns, assign active agent accounts,
configure stages, enroll contacts and remove a membership. Archival is reversible;
removal deactivates only the selected campaign/contact relationship. Neither
operation deletes contacts, notes, source imports, stage references or history.
An agent reads only active campaigns explicitly assigned to their active account,
reads its cards, moves them and appends attributed notes. There is no access to
the global contact directory, import administration, campaign configuration or
other campaigns. Permissions are checked for every request, including nested
contact/notes/event routes. Assignment changes take a campaign row lock, so an
in-flight authorized request completes before revocation and subsequent requests
are denied. No cache or browser-selected campaign authorizes an operation.

Seven initial stages represent new, no-answer, callback, other, appointment,
non-interested and do-not-contact outcomes. Their labels/colors/order are
configurable; their semantic kind and identity remain stable for future provider
outcome mapping. Custom stages can be created and archived once emptied.
Stage order changes validate the whole active stage set and commit atomically.
A composite foreign key prevents a card referencing another campaign's stage.
An appointment stage is classification only: actual appointment creation belongs
to the upcoming calendar module. A callback stage does not schedule a call.

Moving into non-interested or do-not-contact requires explicit confirmation in
the UI and sets the canonical contact flag, then updates every active campaign
membership in one transaction. Global do-not-contact takes precedence over
non-interested. Default restriction stages cannot be archived. Imports and
reenrollment preserve global flags. Clearing flags is a separate, explicit,
administrator-only action with an expected contact timestamp, so a fresh global
restriction cannot be overwritten from a stale confirmation dialog; it does not silently put every membership into a
calling stage. Those cards must be moved deliberately after reactivation.

## Reliability and pagination

Moves carry an expected membership version and a request UUID. The contact row
is locked before its memberships; a concurrent stale move fails with 409 rather
than overwriting the winner. Matching retries return the recorded result without
another move or history event. A reused UUID with a different actor, campaign or
payload is rejected. Global propagation increments all affected versions. New
membership and manual moves receive a fresh queue position, preserving FIFO tail
semantics for the later calling module without claiming call eligibility today.

Enrollment accepts up to 500 explicit contact UUIDs or all successful contacts
from a completed import. A set-based SQL operation locks canonical contacts in a
consistent order, inserts/reactivates memberships, appends per-contact events and
records the idempotent operation result in one transaction. Existing active cards
keep their stage. Duplicate source rows never produce duplicate cards. Invalid
contact selections fail atomically. Bulk enrollment has an explicit 15-second
statement timeout; a failure rolls back instead of claiming a partial success.

Boards return stage counts and at most 20 cards per stage. More cards use an
indexed queue-position cursor. Campaign lists, assignment lists, shared notes
and campaign events are paginated. Notes are shared across memberships of an
accessible contact but do not reveal the names/IDs of unassigned origin campaigns.
Per-campaign event history remains scoped to the selected authorized campaign.
The runtime cannot update/delete/truncate notes or campaign event history.

Notes use an idempotent UUID, have at most 5,000 characters and are rendered as
text. Contact coordinates are read-only in the pipeline. Requests bind to an
explicit campaign and contact ID, not whichever card is currently displayed.

## Migration and deployment

`0004_campaigns` is additive. It does not alter existing contact/import/identity
rows. The preceding compatibility release is
`911177b3181d849115fa5cedd00dd4a21cfcda60`, which accepts schema 3 and 4 while still
checking identity/contact tables and encryption. It must be deployed first.
The installed root deployer then permits the schema-4 image only from that healthy
schema-3 predecessor or an already healthy schema-4 deployment. It keeps all six
services and the same secret/network isolation; there are no new provider secrets.
Rollback restores the preceding app, never a schema downgrade or data deletion.

CI runs populated contact-schema upgrade fingerprint checks, actual HTTP access
and concurrency tests, import/identity regressions, real browser pipeline/note
flows with accessibility and mobile checks, the actual preceding image against
schema 4, and backup/restore fingerprints including campaign tables. The target
of twenty agents still requires later real communications/load acceptance tests.
