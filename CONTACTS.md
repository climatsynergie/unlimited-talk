# Contacts and CSV import delivery contract

## Current implementation boundary

The pure input-validation module `app.contacts.csv_input` is implemented and unit
tested. It normalizes phone numbers, parses bounded CSV data and produces row
results without database mutations. This is preparation, not an activated import
feature: no contact tables, contact API, upload endpoint, worker, broker or S3
credentials are installed by this release. The app does not expose an inactive
import button or claim that any contacts have been imported.

The preceding web image now accepts the explicitly planned additive revision
`0003_contacts`, while still requiring the identity tables, staging marker and
working MFA encryption key. Unknown schema revisions remain unhealthy. Deploy
this compatibility release before applying the actual contacts migration. CI
exercises the compatibility marker with an additive probe and restoration, not
the actual future contacts migration. That migration must be tested separately
with real contact data preservation and application rollback in disposable CI.

## Validated input contract

- Country defaults to CA for numbers without an international prefix. Explicit
  international numbers are supported if structurally valid. Use the maintained
  phonenumbers port of libphonenumber, checking both possible/valid and formatting
  canonical E.164. This does not establish reachability or consent to contact.
- A telephone column is mandatory; first/last/full name, email, street address,
  city, province and postal code are optional. Extensions require an explicit
  direct number rather than being silently discarded.
- Accept UTF-8 including BOM; Windows-1252 is an explicit option. Recognize comma,
  semicolon or tab delimiters, quoted fields and multiline values. The operator
  can override ambiguous separator detection.
- Limit files to 10 MiB, 100,000 data records and 100 columns by default. Reject
  malformed text, null bytes, duplicate/blank headers and invalid mappings.
- Match French/English column aliases only when unambiguous. Each source column
  maps to one allowed profile field. No status/block/permission flags can be
  supplied via CSV mapping.
- Preserve blank values as absent fields, so a later merge cannot erase existing
  data with an empty cell. Keep valid phone rows even when an optional email or
  overlong profile value must be ignored, with a French warning.
- Keep every row result and mark duplicates by canonical phone within the file.
  Database deduplication, enrichment, history and global block preservation must
  be transactional and separately tested; this pure parser does not claim them.

## Next infrastructure and module boundary

Original CSV objects belong in a dedicated private staging S3-compatible bucket
(DigitalOcean Spaces alongside the existing DigitalOcean resources), separate
from PostgreSQL and production. Do not store source files in application images,
repository history or the API's local container filesystem. Do not introduce a
public CDN for these private data sources. Provision least-privilege bucket
credentials through the server's private console/file-secret mechanism, never
chat or GitHub source.

Before activation, configure and verify object privacy, upload/read limits,
TLS, private-network access where available, credentials, recovery and an
explicit retention policy. No source-file deletion schedule is silently chosen
by this preparatory release. Endpoint/region/bucket details are deployment
configuration, not hard-coded public infrastructure metadata.

Imports require a dedicated worker and broker as planned in ARCHITECTURE.md.
Redis/Celery carries task IDs; durable jobs, source fingerprints, mappings,
confirmation, row progress and completion stay authoritative in PostgreSQL.
A broker or worker restart must not lose an accepted import or duplicate work.
Do not replace this with an in-memory API background task.

The activated flow must be: authorized admin upload → validated private source →
column mapping and preview → explicit confirmation → idempotent background apply
→ progress, French row errors and final counters. No contacts change at preview.
Queue admission must survive publication failure via a durable outbox/reconciliation
loop. Lock/lease jobs, commit each row's merge/history/progress atomically and
resume safely after a crash. Keep the application responsive during imports.

The canonical phone identity is global across campaigns. A unique constraint and
upsert must preserve contact IDs/history, ignore blank incoming profile values,
and never clear do-not-contact or non-interested state. CSV content is untrusted:
never interpret formulas or HTML; neutralize spreadsheet formulas in exported
error reports. Do not retry external call/SMS effects as part of import retries.

Contacts administration/import is admin-only. Agents must not acquire a global
contact directory merely because campaign membership is not implemented yet.
Their later contact/note access must check assigned campaigns as already agreed.
No mass deletion, outbound calls or SMS are enabled by the preparation.

## French application language

Visible web and operator messages use French: Préproduction, courriel,
authentification, code QR and account/access labels. Shared form controls supply
French browser validation messages even when the browser's own language is
English. API keys/field names, source code, provider/product proper names and
technical logs need not be translated. Future contact/import UI strings and
validation/errors must follow the same French vocabulary and fr-CA date display.
