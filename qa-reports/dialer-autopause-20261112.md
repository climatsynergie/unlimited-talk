# Automatic dialer pauses — 12 November 2026

Scope: investigate agents reporting pauses after unanswered calls, reproduce the defect, and repair it on `qa/full-audit-20261108`. No production data mutations, deployments, merges, service restarts or real calls were performed for this repair. Base QA revision: `4196dc255cee8f3899611786891d68d45396cda6`.

## Confirmed defects and root causes

**QA-16 — HIGH operational: call-scoped SDK errors pause the automatic queue. Fixed in QA.**

The outgoing controller called `pauseAutomatic()` on every Call error and every Device error, before reconciling the durable outcome. Twilio Voice SDK 2.18.5 may report carrier hangups through Call.error and Device.error with an associated Call. This stopped the queue even when the server subsequently confirmed `no-answer` or `busy`. Eight focused baseline regressions failed before application changes: both event sources, with four durable terminal outcomes.

The fix distinguishes call-scoped errors from device-wide failures. A call-scoped carrier error enters server reconciliation, preserving the running queue. No next reservation is permitted while the current intent is unconfirmed. Once the server confirms the end, the existing full ten-second interval applies. Device-wide, authentication, microphone, signalling and media errors still disarm automatic continuation. The adapter already forwards the SDK callback arguments; the controller's callback types previously discarded their meaning.

**QA-17 — MEDIUM reliability: disconnect hides a following fatal media error. Fixed in QA.**

The pinned SDK can synchronously emit disconnect before its fatal media error. The controller invalidated the media generation on disconnect and ignored the following fatal error. Two focused regressions reproduced this ordering before repair. The final callback accepts the error while the same intent is still being reconciled, deduplicates the pause, and rejects errors from replaced/disposed lifecycles or an earlier intent. This issue existed before this repair.

**Intermediate regression, discovered and corrected before delivery:** the first same-intent implementation could replace a newer Stop or booking hold with Pause. A separate before test run recorded two failures and one pass. The final implementation preserves newer user actions and the server booking hold; fatal errors disarm the eventual booking release. All three regression cases now pass. Failed intermediate evidence is retained.

## Evidence and limits of the live diagnosis

Read-only server checks observed deployed revision `405dc5a611da7795ecac85b7302c54702502e9b8`, schema `0012_incoming_runtime`, health ready and calling enabled. A read-only 36-hour aggregate showed 291 starts, 286 explicit pause actions and 3 stops, with no `dialer.pause_automatic` action. Of the pauses, 77 had a nearest failed call and 43 a nearest unanswered call. These are temporal correlations, not proof that every pause has the same cause, nor a count of SDK errors. Intent-level SDK error telemetry was not available.

Evidence: [read-only command metadata](evidence/dialer-autopause-20261112/readonly-live-diagnosis.json), [aggregate output](evidence/dialer-autopause-20261112/readonly-live-diagnosis.log), and its retained remote script. No customer names, telephone numbers or credential values were queried for this diagnosis.

Primary SDK implementation inspected locally: `frontend/node_modules/@twilio/voice-sdk/es5/twilio/device.js` (`_onSignalingError`, optional associated Call); `call.js` (`_onHangup`, media-handler error/disconnect ordering); `errors/generated.js` (error-code classes). This review used the installed pinned dependency, not assumptions about a different SDK release.

## Coverage and release boundaries

- PASS results and exact executed commands are recorded below; every recorder JSON also includes UTC times, exit code, log hash, source revision and working-diff hash.
- Unit coverage includes unanswered/busy/failed/completed reconciliation, full ten-second delay, server read failure, duplicate and stale callbacks, fatal device/auth/audio failures, explicit pause/stop, presence loss, booking hold/release and lifecycle disposal/reactivation.
- Browser tests run Chromium against the built application. HTTP business responses and the SDK are isolated fixtures; these are real UI/controller/adapter tests, **not** a live provider or fresh HTTP/PostgreSQL end-to-end proof. Unexpected API requests and uncaught browser exceptions are asserted.
- Database/schema: no schema, migrations, backend source or persistence contracts changed in this patch. The live schema was observed read-only. A fresh migration/rollback exercise and database integration suite were **NOT TESTED in this repair**; previous audit evidence remains separate.
- Live carrier audio, agent network conditions, transfers and multi-agent real calls are **NOT TESTED**. A controlled human acceptance test remains required after an authorized release. No real call was initiated.
- Full Foundation CI for the new QA commit is **NOT VERIFIED locally**. No new container image or release has been published by this task. Existing native-library/security and disaster-recovery limitations in the broader readiness reports are not cleared by these tests.
- This patch adds no credentials, permissions, rate-limit bypass, eligibility exceptions, provider requests or automatic redial of an unresolved intent.

## Controlled acceptance after an authorized release

1. With one informed agent, leave an outgoing call unanswered. Verify the server result, the ten-second countdown, and exactly one next call without clicking Reprendre.
2. Repeat with a busy/rejected destination, then an answered call. Check two-way audio and that the displayed contact follows the actual call.
3. During the countdown click Attendre; verify no next call until explicit Reprendre. Check Stop separately.
4. Open a booking form; verify no next call until saving or closing it, and that the booked contact and campaign stage remain correct.
5. Disconnect the agent's network in a controlled test. Verify uncertainty blocks a second call and a persistent failure requires explicit recovery.
6. Repeat the unanswered-call sequence with three agents using separate accounts. Verify one current call per agent and no cross-agent contact or session interference.

**Readiness:** local fix validation does not authorize merging, deploying or real calls. Broader production certification remains subject to the existing unresolved native/carrier/recovery gates. The fix is not active for agents until the reviewed QA change is promoted and deployed through the normal controlled workflow.

## Executed validation

The initial browser attempt used Vite's development server, which bypassed the fixture's built `/assets/twilio-*.js` interception. Both tests failed before establishing a media connection; that run is a **test harness FAIL**, not evidence reproducing the application defect. It is retained as `dialer-autopause-before-browser.{json,log}` with traces and screenshots. Subsequent browser runs use `vite preview` against the production build. The baseline application defect is established by the eight failing unit regressions above.

| Check | Recorded status | Exit | Count | Evidence |
|---|---|---|---|---|
| Baseline call-error regression | FAIL | 1 | 8 FAIL | [metadata](evidence/dialer-autopause-before-unit.json), [log](evidence/dialer-autopause-before-unit.log) |
| Disconnect/fatal ordering before repair | FAIL | 1 | 2 FAIL | [metadata](evidence/dialer-autopause-media-order-before.json), [log](evidence/dialer-autopause-media-order-before.log) |
| Intermediate precedence regression | FAIL | 1 | 1 PASS, 2 FAIL | [metadata](evidence/dialer-autopause-late-fatal-precedence-before.json), [log](evidence/dialer-autopause-late-fatal-precedence-before.log) |
| Final phone controllers | PASS | 0 | 104 PASS, zero skipped | [metadata](evidence/dialer-autopause-final-validated-unit.json), [log](evidence/dialer-autopause-final-validated-unit.log) |
| Backend isolated units | PASS | 0 | 208 PASS | [metadata](evidence/dialer-autopause-backend-unit.json), [log](evidence/dialer-autopause-backend-unit.log) |
| Host tools | PASS | 0 | 23 PASS | [metadata](evidence/dialer-autopause-host-regression.json), [log](evidence/dialer-autopause-host-regression.log) |
| Final TypeScript/build | PASS | 0 | PASS | [metadata](evidence/dialer-autopause-final-validated-build.json), [log](evidence/dialer-autopause-final-validated-build.log) |
| Final formatting | PASS | 0 | PASS | [metadata](evidence/dialer-autopause-final-validated-format.json), [log](evidence/dialer-autopause-final-validated-format.log) |
| Final browser journeys | PASS | 0 | 37 PASS | [metadata](evidence/dialer-autopause-final-validated-browser.json), [log](evidence/dialer-autopause-final-validated-browser.log) |

Commands below ran from `/home/codexdev/unlimited-talk-qa-audit`. The Vite preview server was started separately from `frontend/` with `npm exec -- vite preview --host 127.0.0.1 --port 15174 --strictPort`.

### Baseline call-error regression — FAIL, exit 1

```sh
node --experimental-strip-types --test '--test-name-pattern=erreur (call|device-call), résultat serveur' frontend/tests/phone-controller.unit.ts
```

### Disconnect/fatal ordering before repair — FAIL, exit 1

```sh
node --experimental-strip-types --test '--test-name-pattern=déconnexion puis erreur audio' frontend/tests/phone-controller.unit.ts
```

### Intermediate precedence regression — FAIL, exit 1

```sh
node --experimental-strip-types --test '--test-name-pattern=erreur audio tardive préserve' frontend/tests/phone-controller.unit.ts
```

### Final phone controllers — PASS, exit 0

```sh
npm --prefix frontend run test:phone
```

### Backend isolated units — PASS, exit 0

```sh
sudo -n docker --host=unix:///var/run/docker.sock run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -e PYTHONDONTWRITEBYTECODE=1 -v /home/codexdev/unlimited-talk-qa-audit/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro -v /home/codexdev/unlimited-talk-qa-audit/scripts:/scripts:ro unlimited-talk-qa-audit:dependency-hardened python -m unittest discover -s /tests -p 'test_*.py' -v
```

### Host tools — PASS, exit 0

```sh
python3 -m unittest discover -s tests/host -p 'test_*.py' -v
```

### Final TypeScript/build — PASS, exit 0

```sh
npm --prefix frontend run build
```

### Final formatting — PASS, exit 0

```sh
npm --prefix frontend run format:check
```

### Final browser journeys — PASS, exit 0

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=dialer-autopause-final QA_BROWSER_OBSERVATIONS=/home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/dialer-autopause-final-observations.jsonl npm --prefix frontend run test:browser -- tests/autodialer.spec.ts tests/phone.spec.ts tests/incoming.spec.ts tests/incoming-session.spec.ts
```

Final browser observations: 37 recorded journeys, zero uncaught JavaScript exceptions. Expected negative HTTP/session errors remain in the retained observations; they were not suppressed. Browser traces/screenshots from failed baseline-harness attempts are retained.

Raw evidence stays local under ignored `qa-reports/evidence/`; no secret-scan bypass or raw fixture upload is used. Reproducible test source and this report are committed.
