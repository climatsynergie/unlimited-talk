# Agenda day-header downloads — 22 November 2026

The user requested moving the working TXT controls from a separate weekly panel
to each actual agenda day's heading. The separate section and its empty-day
buttons are removed. A single compact TXT button now shares the row with each
day's date, above that day's appointments. Other calendar views and conversation
filters retain their behavior. Backend code, export data, permissions, filters,
file format, authentication, dependencies and schema are unchanged.

The existing download logic now lives in a calendar-owned hook. FullCalendar's
official listDayHeaderContent callback renders the control; no imperative DOM
injection or vendor library patch. In-flight downloads still abort on filter,
period/view changes and unmount, with shared pending/error state. Native list
semantics and appointment interactions are retained.

Executed evidence is under qa-reports/evidence/ with exact commands, source
context, times, exit codes and output hashes in paired JSON/log records. Commands
use `python3 qa-reports/tools/run_check.py <name> -- <command>`:

| Evidence prefix | Command after recorder prefix | Result |
|---|---|---|
| `agenda-inline-layout-build` | `npm --prefix frontend run build` | PASS / exit 0; TypeScript and Vite |
| `agenda-inline-format` | `npm --prefix frontend run format:check` | PASS / exit 0 |
| `agenda-inline-browser-final` | Recorded local Vite URL; Playwright `call-history.spec.ts team-calendar.spec.ts calendar-reconfirmation.spec.ts` | PASS / exit 0; 20 tests, before final max-width refinement |
| `agenda-inline-real-browser-final` | Recorded absolute isolated Compose paths; `python3 tests/verify_browser.py identity.spec.ts --grep 'conversations et agenda'` | PASS / exit 0; real Chromium → HTTPS/API → migrated PostgreSQL threshold and TXT journey, before final max-width refinement |
| `agenda-inline-layout-browser` | Recorded local Vite URL; Playwright `team-calendar.spec.ts --grep 'agenda : téléchargement'` | PASS / exit 0 on final layout, including date/button bounding-box alignment, one button per displayed day, filter propagation, download contents, retry, Toronto/Vancouver day identity, mobile width, Axe and removal in week view |

A new synthetic Compose project, ut-qa-agenda-inline-20261122, uses disabled
communications, local db and current source/dist mounted over the cached hardened
dependency image; schema12 migrations and API readiness passed. It is not a new
release-image build or a live telephony test.

Preserved attempts: `agenda-inline-browser` failed because FullCalendar rendered
two header levels, producing duplicate buttons. The callback now renders only
level zero; the exact-one-button assertion was retained. `agenda-inline-browser-single-button`
then passed all 20 tests. Visual review found the inherited theme max-width still
wrapped the control; scoped CSS resets it, and the final geometry assertion now
verifies horizontal placement. The first `agenda-inline-real-browser` scenario
printed one pass but its launcher exited143 before complete health restoration;
that incomplete attempt is not a successful full harness run. The subsequent
complete final run exited0. Earlier screenshots/traces/logs are retained.

Screenshots inspected include
`evidence/browser-artifacts/agenda-inline-layout-20261122/team-calendar-agenda-téléc-e9e17-vés-et-reprise-après-erreur/agenda-inline-desktop.png`
and its mobile counterpart. The backend is byte-identical to the preceding,
fully validated release; no unnecessary backend changes or speculative fixes.

At preparation: exact candidate CI/provenance/publication/deployment pending,
not PASS. Live real calls, load testing and Safari/Firefox were not executed.
The normal unchanged deployment guard must reject active calls. The known single
API replacement limitation remains; zero-downtime deployment is not claimed.
