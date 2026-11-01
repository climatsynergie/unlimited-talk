# Client qualification

The source questionnaire is the legacy application release of 20 October 2026,
`unlimited_talk_qualification.py`. Its exact choices, conditional questions and
required fields are preserved in `backend/app/qualification-v1.json`. The
calendar's existing date/time controls supply legacy question 13, and the
authenticated appointment creator supplies “Booker par” (question 15).

| Question | Required for booking |
| --- | --- |
| Client propriétaire du logement | Yes |
| Nombre de propriétaires | When the client is an owner |
| Type de propriété | Yes |
| Nombre d’étages hors sous-sol | Yes |
| Présence et état du sous-sol | Yes |
| Système de chauffage | Yes; heating comment optional |
| Âge du chauffage | Yes |
| Présence et type de thermopompe | Yes; heat pump comment optional |
| Thermopompe murale à tous les étages | When a wall-mounted heat pump is present |
| Âge de la thermopompe | When any heat pump is present |
| Travaux ou améliorations de l’isolation | Yes |
| Accès au grenier / entretoit | Yes |
| Numéro civique, rue, ville et code postal | Yes |
| Commentaires pour le conseiller | Yes |

No answer is guessed. Imported address fields can prefill the corresponding
inputs. Hidden conditional answers are discarded. Postal codes are validated
and normalized on the server. Only schema version 1 and the declared string
fields are accepted, with bounded lengths and fixed option lists.

## Persistence and concurrency

Qualification is a versioned, immutable business snapshot in PostgreSQL, using
the existing protected event streams. It is never encoded in free-text notes.
The indexed `campaign_events(campaign_id,contact_id,id)` projection selects the
latest `contact.qualification_saved` snapshot. The event ID is an opaque string
revision: concurrent editors submit their expected revision and receive 409 on
a conflict. Request IDs make an uncertain save retry idempotent. Campaign and
contact access are checked on every write, including replay.

`PUT /api/campaigns/{campaign}/contacts/{contact}/qualification` saves a partial
or complete snapshot independently of scheduling from the campaign contact view.
Saving does not change the pipeline or pause the dialer. The live call sheet has
one booking path: qualification alone never pins the previous contact and needs
no separate save. Without a booking, automatic calling displays the next contact
and discards that unsaved qualification. Clicking the booking action holds the
dialer for date/time confirmation; only confirmation persists the responses with
the appointment. Notes, callbacks and in-flight operations retain their existing
draft protection. A conflicting booking preserves answers until explicit reload.

`POST /api/calendar` requires a complete qualification and the expected contact
qualification revision. It atomically records the qualification, appointment,
callback cancellation and pipeline move. The appointment's event stream retains
its own snapshot, independently of later client edits. The existing per-appointment
index selects the newest qualification-bearing create/update event. Scheduling
edits preserve that snapshot unless a complete replacement is explicitly supplied.
The booking form defaults to Quebec time (`America/Toronto`) and displays the
authenticated booker. The actor is assigned by the API, never by an editable field.

Existing appointments without qualification remain readable and can be rescheduled
or cancelled. Reconfirming a cancelled, unqualified appointment requires the form.
This change adds typed snapshots to existing JSONB event payloads; it introduces
no schema migration, event rewrite, legacy data import or telephony configuration.
