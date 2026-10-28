# Shared calendar contract

## Confirmed behavior

The application owns its calendar, contacts and appointment history; it has no
GoHighLevel dependency. The shared calendar is named **Unlimited Talks**.
All active agents and administrators can view its appointments, including those
created in other campaigns. Agents create appointments for contacts in their
assigned active campaigns and may edit or cancel appointments they created.
Administrators may edit or cancel every appointment. Seller accounts and seller
assignment are outside the first calendar release.

An appointment records its contact, campaign of origin, creator, start date and
time, duration, IANA timezone, notes and status. Multiple appointments may overlap
because several sellers can handle them. Cancellation preserves the appointment
and its history. Creating a calendar appointment must not contact Twilio, send an
SMS, or create a meeting in an external provider.

## Proposed implementation contract

These are implementation choices for the upcoming module, not delivered features:

- Store start and end as PostgreSQL `timestamptz` in UTC, alongside the original
  IANA timezone. Browser entry explicitly names the appointment timezone;
  viewing in another timezone never changes the stored instant. Reject missing
  timezone, nonexistent daylight-saving times, and ambiguous times until the
  user explicitly chooses the UTC offset. Validate end after start on server
  and in database. Default creation timezone is the campaign timezone.
- One shared calendar, backed by appointment and append-only event tables.
  Preserve contact/campaign/creator foreign keys and record every create,
  reschedule, note change and status transition with actor and timestamp.
  No hard-delete endpoint or runtime permission to alter appointment history.
- Initial statuses: `booked` (RDV booké), `completed` (Terminé),
  `cancelled` (Annulé), `no_show` (Absent). Status changes are explicit and
  audited. A cancelled appointment is excluded from upcoming views by default,
  with an option to show it. No automatic pipeline reversal on cancellation:
  another appointment may exist for the same contact.
- Create the appointment and move its campaign membership to the semantic
  `appointment` stage in one transaction, recording both histories. Current
  manual moves into RDV booké remain classifications and must never invent
  appointments. Block booking from an archived/unassigned campaign or an
  inactive membership. A new booking does not silently clear a global contact
  restriction; require administrator reactivation first.
- Use an idempotency UUID on creation and optimistic version checks on updates.
  Duplicate retries return the original result, mismatched UUID payloads and
  stale edits return conflict responses. Agent identity and permissions always
  come from the server session, never client-supplied creator fields.
- Shared visibility is specific to appointment data, including contact details
  needed for the meeting. It must not grant access to other campaigns' boards,
  imports, private contact directory or unrelated campaign history. Revoking
  campaign assignment prevents new bookings there; ownership permission for
  existing appointments follows the agreed creator/admin rule.
- Provide bounded date-range queries, pagination and indexes on start time,
  contact and creator. Display a French week view plus an accessible agenda
  view on small screens, with filters for creator and status. Show overlaps
  without treating them as resource conflicts. Do not silently truncate results.

## Rollout prerequisite (this release)

The campaign app now accepts both `0004_campaigns` and the explicitly planned
`0005_calendar` readiness revision. Its own migration head and image label remain
`0004_campaigns`. No calendar tables, appointment API or calendar UI are present
in this preparation release. Unknown revisions still fail readiness.

The disposable compatibility probe temporarily adds a synthetic table and changes
only the local database revision marker to verify readiness across the planned
schema boundary, then restores the original marker and removes the probe. It
refuses managed PostgreSQL. This is a compatibility check, not a test of an actual
calendar migration.

Deploy this compatibility release through successful main CI and the attested
Deploy staging workflow, then verify its exact running revision. Record that SHA
as the required schema-4 predecessor in the reviewed host deployer before allowing
the schema-5 migration. Develop the actual calendar migration and functionality
on a feature branch while main remains deployable at the prerequisite SHA.

Before calendar promotion, test timezone/DST entry, permission boundaries,
concurrent edits, duplicate creation retries, atomic appointment/pipeline changes,
appointment overlaps, history immutability, populated schema-4 upgrade, actual
application rollback against schema 5, and backup/restore of all calendar data.
The rollback preserves schema 5 and all appointments; it does not downgrade data.
