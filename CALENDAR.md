# Shared calendar

The application owns the **Unlimited Talks** calendar. No GoHighLevel or external
calendar service is involved. All authenticated active agents and administrators
can view its appointments, including appointments originating in other campaigns.
Agents create appointments for contacts in their assigned active campaigns and
edit or cancel their own appointments. Administrators edit or cancel any meeting.
Seller accounts and seller assignment are not part of this release.

## Booking and history

Appointments preserve contact, campaign of origin and creator references, UTC
start/end instants, IANA timezone, notes, status, version and timestamps. Multiple
appointments may overlap. Durations are 5–1440 minutes; date entry supports years
2000–2100 at minute precision. Browser entry explicitly names its timezone,
defaulting to the campaign timezone. Viewing in another timezone changes only the
display. Display includes the UTC offset for ambiguous fall-back hours.

The browser asks `/api/calendar/resolve` for valid instants for a local wall-clock
time. The server round-trips both DST folds through UTC. Nonexistent spring times
are rejected; repeated autumn times require the user's explicit offset selection.
The creation/update endpoint independently performs the same validation and rejects
an invalid or missing ambiguous offset. The selected offset is reflected in the
stored UTC instant; the timezone is stored separately. Duration is elapsed time.

Creation and movement to the campaign's semantic `appointment` stage occur in one
PostgreSQL transaction, with a campaign event and appointment event. Failed writes
roll back the entire booking. Current membership version is required to prevent a
stale form from overwriting a concurrent pipeline action. New bookings refuse
archived/unassigned campaigns, inactive memberships and globally restricted
contacts. An administrator must explicitly reactivate a restricted contact first.

A client-generated UUID identifies creation attempts. The server records an exact
normalized payload hash and creator. Identical retries return the existing meeting
without a second stage move or audit event; reusing the UUID with another payload
or creator is a conflict. Updating requires the current appointment version and a
row lock. Concurrent editors get a 409 rather than silently losing changes.

Statuses are `booked` (RDV booké), `completed` (Terminé), `cancelled` (Annulé) and
`no_show` (Absent). Status changes and date/duration/timezone/note edits are explicit,
with immutable before/after history and actor/timestamp. Cancellation keeps all
data and does not reverse a pipeline stage: another meeting may exist. Manual
movement into RDV booké remains a classification and never invents an appointment.
No booking operation places a call, sends an SMS or contacts an external provider.

Appointments remain visible and their creator retains editing rights after
campaign unassignment or archival. Those actions prevent new bookings there. The
shared calendar permission grants only appointment-related contact coordinates;
it does not grant another campaign's board, imports or unrelated history.

## API and interface

All endpoints use the existing session, CSRF and exact-origin protections:

- `GET /api/calendar/resolve?local_start=...&timezone=...`: valid UTC candidates.
- `GET /api/calendar?start=...&end=...`: overlapping appointments in a bounded
  period (maximum 93 days), ordered by start/id. Optional creator/status filters,
  `exclude_cancelled`, and offset pagination, 100 items/page with `has_more`.
- `POST /api/calendar`: `id`, campaign/contact ids, membership version, naive
  `local_start`, timezone, optional UTC offset minutes, duration minutes and notes.
- `GET /api/calendar/{id}`: appointment, creator/admin edit permission and paged
  immutable history; `before` is the history cursor.
- `PATCH /api/calendar/{id}`: full schedule/notes/status plus expected version.
  Contact, source campaign and creator cannot be reassigned through this endpoint.

French `/calendrier` navigation is available to agents and admins. It provides an
agenda and a seven-day view, timezone selector, all/mine creator filter, status
filter, explicit pagination and refresh. Cancelled entries are hidden by default
using a server-side filter. The week view becomes an agenda on narrow screens.
Open a campaign contact and choose **Prendre rendez-vous** to book. The editor
keeps entered values on error; it closes only after a successful save or explicit
cancellation of entry. Cancelling entry does not create a meeting.

## Database and delivery

Migration `0005_calendar` adds `appointments` and append-only `appointment_events`.
Existing tables/data are preserved. Time, creator and contact indexes support
bounded queries. The runtime role cannot delete meetings or modify/delete/truncate
appointment events. There is no automatic schema downgrade.

Compatibility predecessor **0601ff555cc27e07057a499ac37ba349e399650e** was verified
healthy on managed staging before calendar development. It accepts schemas 4 and 5.
The reviewed root deployer requires that exact healthy schema-4 predecessor or an
already healthy schema-5 release. The container template, secrets and networks are
unchanged. Deploy only the exact main commit with successful tests, publication
and provenance through Deploy staging. Application rollback preserves schema 5
and every appointment; the old application simply has no calendar screen.

Disposable tests cover DST gaps/overlaps, permission boundaries, duplicate booking
retries, concurrent updates, pipeline transitions, overlapping meetings, immutable
history, populated schema-4 migration, browser booking/reschedule/cancel/mobile
accessibility, real predecessor rollback, backup/restore and database recovery.
Managed staging verification still requires the actual deployment and user
acceptance. These checks do not constitute a 20-agent load test.
