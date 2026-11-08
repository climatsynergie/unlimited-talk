# Frontend audit evidence and residual coverage gaps

Scope: candidate `96f5055b7fff29257a0e306e0658721394cc80a7`, QA branch `qa/full-audit-20261108`. Original frontend on local HTTP lab18204 matches baseline662. No production data or provider operations were used. Final release judgement belongs to the consolidated report; a mocked browser flow cannot verify carrier audio, webhook delivery or actual multi-agent telephony.

## System inventory (static inspection)

Public identity workflows include login, invitations, password reset, MFA enrolment and recovery. Authenticated navigation contains fourteen pages:

| Audience | Paths | Important interactions |
|---|---|---|
| Administrator | `/admin/tableau-de-bord`, `/admin/utilisateurs`, `/admin/invitations`, `/admin/journal`, `/admin/contacts`, `/admin/imports` | Live/daily/hourly agent reporting and export; account/role changes; invite links; audit history; contacts; CSV upload, preview, mapping and job progress |
| Agent and administrator | `/accueil`, `/compte`, `/campagnes`, `/calendrier`, `/rappels`, `/appels-entrants`, `/poste-appel`, `/conversations` | Password/session controls; campaign stages and assignments; qualification and appointments; callbacks; incoming reception; outgoing manual/automatic calls; recording history/search |

Critical interface rules include persistent call media across navigation, explicit incoming acceptance, stale-session media shutdown, no automatic reconnection after logout/recovery, backend-authoritative call occupancy, ten-second automatic-call wrap-up, callbacks before ordinary campaign contacts, global do-not-contact restrictions, separate English handoff, voicemail outcome/reporting, conditional required appointment qualification, optimistic revisions and timezone-aware schedules.

Providers own the outgoing/incoming controller lifetimes globally. The incoming controller registers browser media, advertises availability through heartbeats, resolves canonical server offers, obtains explicit user acceptance, and reconciles uncertain terminal events. The outgoing controller distinguishes manual/automatic reservations and delays the next call after terminal confirmation. External media is dynamically loaded through the Twilio SDK. All new browser tests intercept that SDK and every business API request.

## Confirmed defects and repairs

| Reference | Suggested severity | Reproduction / original behavior | Root cause / minimal repair | Regression |
|---|---|---|---|---|
| FE-IN-01 | HIGH | Accept an incoming call while the second initial registration heartbeat is pending, then fail that heartbeat. Accepted audio is destroyed. | Startup catch treated late control-plane error as failed media setup. Preserve known offered media and pause future availability. | `incoming-controller.unit.ts`: late initial heartbeat failure test |
| FE-IN-02 | MEDIUM | Start an empty session request, receive/accept a new incoming call, then disconnect its local media before the older empty response returns. New offer and busy state are incorrectly cleared. | `prepare()` lacked offer/registration context generation. Ignore responses if that context changed during the request. | `incoming-controller.unit.ts`: older empty session/newer uncertain offer test |
| FE-IN-03 | HIGH | During an accepted incoming call click logout while the API is pending or fails. The original incoming microphone/device remains active. | Workspace explicitly disposed outgoing media only. Dispose both directions before awaiting logout; failed logout recovers paused server state without creating another device. | `incoming-session.spec.ts`: delayed500 logout, disconnect/destroy before releasing HTTP response, manual terminal reconciliation |
| FE-IN-04 | HIGH | Change own password during an accepted incoming call. Backend rotates every session while the same-user keyed provider retains the old session-bound controller/media. | Replace both controller instances on successful own password rotation, with cleanup in provider layout effect, preserving Account confirmation state. Backend session ownership stays strict. | `incoming-session.spec.ts`: same-user successful password rotation closes old media and does not auto-register another device |
| FE-CAL-01 | MEDIUM frontend / coordinated backend finding | A historical appointment without qualification can be changed from completed/no_show to booked without showing the mandatory qualification form. | Qualification trigger considered cancelled only. Require form for every nonbooked-to-booked transition; backend reviewer owns matching authoritative guard. | `calendar-reconfirmation.spec.ts`: completed, no_show and cancelled; native required-field validation, zero premature PATCHes, submitted qualification payload |

## Executed evidence

Exact argv, working directory, UTC and process exit code are recorded in matching JSON files. Logs contain raw stdout/stderr; Playwright failure directories include traces and error context. All paths below are relative to `qa-reports/evidence/frontend/`.

| Run | Outcome | Counts | Evidence |
|---|---|---|---|
| Controller regressions before repairs | FAIL, exit1 |46 total /44PASS /2FAIL | `controller-before.json`, `controller-before.log` |
| Controller regressions after repairs | PASS, exit0 |46PASS | `controller-after.*`, repeated after all frontend edits as `final-controller.*` |
| Fully mocked baseline browser regression set | FAIL, exit1 |5 total /1PASS /4FAIL | `browser-confirmed-before.json`, `.log`, `browser-confirmed-before-artifacts/**/trace.zip` |
| Fully mocked fresh-build browser regression set | PASS, exit0 |5PASS | `browser-after.json`, `.log` |
| TypeScript check and Vite production build | PASS, exit0 | Build, no test count | `build.json`, `build.log` |

Earlier browser-before and browser-baseline logs document fixture-development attempts: one ambiguous status locator was corrected without changing the application; a default maxFailures1 run stopped early. These are retained transparently and are not counted as verified application defects. The final baseline five-test run above has only intended application assertions failing.

Fresh-build browser after-repair execution completed against isolated lab18304: **PASS5/5, exit0**, recorded in `browser-after.json/.log` (18.7 seconds reported by Playwright). This is browser/UI execution with fully mocked business API and media transport; it does not claim real provider or database coverage.

## Coverage limits found in discovery

- Existing incoming browser tests were entirely API/SDK mocked. They did not exercise real browser/API/database/provider reception together. New regressions add lifecycle/state coverage, not real audio proof.
- Existing browser configuration disables trace, screenshots and video by default and lacks a suite-wide unexpected-console/network collector. The parent owns the audit-only evidence configuration and full-run error collection.
- Existing accessibility checks cover selected rendered pages and viewports, not every modal/state. New lifecycle tests do not substitute for the broader accessibility pass.
- Password/session rotation, delayed/failed logout, late startup heartbeat and stale reception snapshots lacked regression tests; the tests above close those narrow gaps.
- Browser refresh/reopen, expired SDK token, lease loss, queued incoming calls during simultaneous outbound dialing, real recordings, and three/twenty simultaneous agents require integration-specific execution and must stay BLOCKED/NOT TESTED unless separately evidenced by the parent run.
- Incoming receiver SDK/native-media failures can surface an English exception message; low-severity French localisation gap remains a residual review item (not repaired speculatively).
- An incoming offer bar shows queue and phone; it has no direct contact qualification/appointment action. This is a product workflow question, not a confirmed broken contract.
- Calendar agent filter options are derived from the loaded date window. Selecting a person whose appointments exist only outside the window may require navigation; product behaviour needs explicit acceptance before calling it a defect.
- No real PSTN, SMS, production mutations or deployment performed by this reviewer. Carrier audio, public callbacks, browser permission policy and live external credentials remain separate release gates.

## Additional asynchronous UI review

Static inspection of `Campaigns`, `Callbacks`, `Contacts` (imports), `Dashboard`, `App`, `api`, `AutoDialer` and `CallHistory` found these protections: page-context GETs carry abort signals, and `api()` checks aborted status again after JSON parsing; callback creation retains its UUID for an unchanged retry and rotates it when fields change; DST resolution aborts obsolete choices; import job polling schedules its next timeout only after the previous read settles; dashboard live/overview/detail loaders enforce single in-flight requests, timeouts, visibility-aware refresh and effect cleanup. Browser back/forward updates the selected workspace page, while global call controllers stay above page content. These are code-review observations, not executed pass results.

The following adversarial UI combinations remain **NOT TESTED by this frontend reviewer** and should be checked against the consolidated execution inventory before release:

| Area | Remaining dynamic scenario |
|---|---|
| Campaign navigation | Delayed pagination/move response while returning to campaign list and selecting a different campaign |
| Callback/appointment mutation | Lost successful HTTP acknowledgement followed by unchanged retry, edited retry and page navigation |
| Imports | Switching selected job during row retrieval, polling503 then recovery, navigation/unmount during upload, duplicate confirm following lost acknowledgement |
| Dashboard | Slow filter/agent A response after switching to B; interval refresh during filter submission; export cancellation/navigation and malformed export response |
| History/navigation | Back/forward or refresh with dirty qualification/notes and an in-flight mutation; interrupted pagination with selected conversation |

No additional confirmed high defect was established from these paths; no speculative source changes were made.

## Coordinated reporting defect (incoming activity omitted)

The backend reviewer reproduced in PostgreSQL that incoming historical activity was zero and an incoming-only administrator was absent from the live roster (`evidence/backend/reporting-gap-probe.log`, original exit1). Dashboard source had no incoming metric contract/display. In coordination, the backend now supplies separate zero-default `incoming_calls`, `incoming_answered`, and `incoming_talk_seconds` at totals, agent, daily and hourly scope; existing outgoing fields retain their original meaning.

The frontend repair displays incoming propositions, answered calls and known talk duration as separate KPIs, comparison/daily columns and hourly detail. The chart footnote explicitly identifies outgoing graphs and explains that one incoming call can create one proposition per agent. An incoming-only administrator from the live API is displayed without filtering them out. No outgoing counts or ratios are recomputed on the client.

Two additional browser regressions in `dashboard.spec.ts` both FAIL on baseline at the absent incoming cards (`dashboard-before.json/.log`, screenshots and traces under `dashboard-before-artifacts`). They verify distinct synthetic incoming7/3/95 against outgoing24/12/720, hourly/day/agent breakdown, incoming-only administrator visibility, and zero defaults for an older report response. The fixture now rejects unknown APIs with404 and records unexpected requests, rather than silently replying with an empty object. `reporting-build.json/.log` records TypeScript/Vite PASS, exit0. Passing-after reporting evidence is now executed: all6 dashboard browser tests (including the2 new reporting tests and existing mobile/Axe checks) pass in the parent’s corrected main suite (`evidence/post-dispatch-browser.log`, `browser-recheck-results.json`). Frontend source is frozen; hashes are in `evidence/frontend/source-manifest.json`.

## Coverage-driven incoming controller verification

After the initial V8 coverage review identified unexecuted token-renewal and explicit decision-error branches, six focused unit scenarios were added without application changes. They execute actual idle token replacement and SDK re-registration; three token network failures followed by pause and explicit retry; deferred token completion after disposal with and without a new receiver; rejected incoming media with a lost decision acknowledgement; and failed acceptance retaining durable occupancy until terminal confirmation.

`npm run --prefix frontend test:phone` executed against unchanged application code: **52PASS,0FAIL, exit0**, recorded in `evidence/frontend/expanded-controller.json/.log`. These scenarios validated existing behaviour and did not reproduce an additional defect. The fixture records token-update and registration operations, allowing assertions on media effects rather than treating an API request as sufficient evidence. Updated coverage percentages must come from the parent’s executed coverage run; no new percentage is inferred here.


## Final frontend verification handoff

The parent’s corrected main browser run is65PASS/3SKIP/0FAIL. Separately executed gated real-agent2 and real-incoming1 cases pass; their actual commands/results are tracked by the parent and must not be inferred from mocked media tests. After the final one-line reception-card spacing repair, the focused real incoming workflow and error/accessibility scenarios pass2/2. Computed browser padding is24px on every side at390px and1440px, and both after screenshots were inspected. FE-VIS-01 is closed verified; details/hashes are in `evidence/frontend/visual-review.md` and `reception-padding-after.json`.

Expanded controller coverage was actually executed by the parent with52PASS: incoming85.87% lines/62.64% branches, outgoing92.29% lines/80.08% branches (`evidence/final-controller-coverage-retry-20261108T232501298774.log`). These figures describe the two controller files only, not the entire frontend. Untested branches and integration limits remain explicit; a percentage is not a release guarantee.

All captured browser observation sets were read and classified: `browser-observations-first-classified.json` retains the original failures; `browser-observations-recheck-classified.json` records the corrected main run; `browser-observations-padding-classified.json` records the final focused cosmetic rerun. No unexplained browser error or uncaught exception remains in the latter two sets. The visual review records26 actual screenshot examinations, including original failures and one explicitly partial fine-text review of an oversized callback capture.

No deployment, production data mutation, live carrier call or SMS was performed by this frontend reviewer. Final release readiness and third-party/OS advisory decisions belong to the consolidated release report.

Consolidated final source/test fingerprints are in evidence/final-repository-source-hashes.json and evidence/final-source-manifest.json; the earlier scoped frontend/source-manifest.json is an initial snapshot, superseded after the52-test expansion and cosmetic spacing repair.
