# Direct callbacks from incoming lists and conversations — 15 November 2026

Isolated QA worktree based onfbe5d64; frontend-only change. No database, HTTP contract, provider profile, queue assignment or telephony controller modification. No real calls or production records were created by these checks.

## Behavior

Incoming follow-up list and pipeline cards now expose a green **Rappeler** action alongside the explicit **Fiche client** link. A direct callback opens the same client sheet with available canonical imported coordinates, shared notes, status and incoming history. Incoming call history also displays the known caller’s name and offers direct callback plus the client sheet, including answered callers without a follow-up. Unknown callers retain the visible number and can be called without silently creating a contact.

The selected outbound conversation now exposes **Rappeler**, **Raccrocher** and **Boîte vocale** using the existing persistent PhoneController. Manual calls require no original campaign membership. The existing active call bar survives closing a sheet/navigation; another active call/incoming occupancy or running automatic sequence prevents starting another manual call. An explicit pause action remains available in the sheet/conversation controls. No automatic claim, handled status, appointment or note is invented by the callback button.

A shared `Recall.tsx` component keeps busy/phone availability/number checks, errors, pause, hangup and voicemail consistent. Incoming DNC flags disable direct callback; the existing authoritative server also refuses DNC from conversation history where only the historical destination is available. Non-interested contacts remain manually callable as previously requested. Reservation errors remain visible and retryable. The API’s existing manual caller-number selection applies; no claim of changing the outgoing line to match the received number.

React review: hooks unconditional, one page-level initial phone refresh rather than per-row network requests, stable keyed rows/ids, sibling buttons instead of nested interactive controls, static accessible labels, descriptive disabled-state hints, and shared controller admission/duplicate protections. Imported profile values remain React-escaped; no new contact read endpoints or authorization expansion.

## Actual test results

- Baseline after starting preview: missing direct action reproduced in Chromium (15s locator timeout). Initial earlier attempt failed because preview was stopped; preserved as a harness error, not a product reproducer.
- First surrounding suite:35 PASS /1 FAIL. The new disabled-state hint had inadequate text/background contrast in the conversation screen. Scoped hint color darkened to#5c5268; original WCAG assertion retained.
- Final surrounding Chromium suite: **40 PASS /0 skipped** across incoming callback/client sheet, history, reception/session recovery and persistent outgoing phone workflows. Tests include list/pipeline/received history one-click callbacks, correct client details, manual history callback with no campaign, double-click one reservation, hangup, DNC refusal before SDK, unknown/hidden callers, failed reservation retry, audio/navigation/session cleanup, mobile overflow and axe WCAG2A/AA/2.1AA.
- Existing controller/installed SDK suite: **159 PASS /0 skipped**. No controller implementation changes.
- TypeScript/production build and formatting PASS. Exact current frontend source built; tests use synthetic business-API and lazy SDK boundaries, not live carriers.
- Mobile screenshots and traces retained locally under `qa-reports/evidence/`; no personal production data in fixtures. A screenshot was initially mislabeled conversation/mobile while captured in the incoming desktop error fixture; retained as `direct-recall-inbound-error-desktop.png`, and a subsequent focused capture corrects the placement. The mobile axe/overflow test itself had already passed.

## Evidence and exact commands

### direct-recall-before: FAIL, exit 1

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=direct-recall-before npm --prefix frontend run test:browser -- inbound-callback.spec.ts --grep 'rappel direct entrant depuis Liste'
```

[metadata](evidence/direct-recall-before.json), [log](evidence/direct-recall-before.log).

### direct-recall-before-running-preview: FAIL, exit 1

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=direct-recall-before-running npm --prefix frontend run test:browser -- inbound-callback.spec.ts --grep 'rappel direct entrant depuis Liste'
```

[metadata](evidence/direct-recall-before-running-preview.json), [log](evidence/direct-recall-before-running-preview.log).

### direct-recall-browser: FAIL, exit 1

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=direct-recall QA_BROWSER_OBSERVATIONS=/home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/direct-recall-observations.jsonl npm --prefix frontend run test:browser -- inbound-callback.spec.ts call-history.spec.ts incoming.spec.ts incoming-session.spec.ts phone.spec.ts
```

[metadata](evidence/direct-recall-browser.json), [log](evidence/direct-recall-browser.log).

### direct-recall-browser-final: PASS, exit 0

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=direct-recall-final QA_BROWSER_OBSERVATIONS=/home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/direct-recall-final-observations.jsonl npm --prefix frontend run test:browser -- inbound-callback.spec.ts call-history.spec.ts incoming.spec.ts incoming-session.spec.ts phone.spec.ts
```

[metadata](evidence/direct-recall-browser-final.json), [log](evidence/direct-recall-browser-final.log).

### direct-recall-phone-unit: PASS, exit 0

```sh
npm --prefix frontend run test:phone
```

[metadata](evidence/direct-recall-phone-unit.json), [log](evidence/direct-recall-phone-unit.log).

### direct-recall-build-final: PASS, exit 0

```sh
npm --prefix frontend run build
```

[metadata](evidence/direct-recall-build-final.json), [log](evidence/direct-recall-build-final.log).

### direct-recall-format: PASS, exit 0

```sh
npm --prefix frontend run format:check
```

[metadata](evidence/direct-recall-format.json), [log](evidence/direct-recall-format.log).

## Release limitations

Exact new-source full main CI, image publication/provenance and deployment are pending at report creation. Live PSTN/audio/headset acceptance for these new entry points is NOT TESTED; no live call was initiated by the agent. Backend integration and database behavior are unchanged; the required complete CI will still execute their existing gates. This scoped validation does not override the wider formal production-readiness limitations.

## Focused mobile evidence capture: PASS, exit0, two tests

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=direct-recall-mobile npm --prefix frontend run test:browser -- inbound-callback.spec.ts --grep 'conversation : erreur visible|liste entrante : actions visibles'
```

[metadata](evidence/direct-recall-mobile-evidence.json), [log](evidence/direct-recall-mobile-evidence.log). Both screenshots were visually inspected after correction.
