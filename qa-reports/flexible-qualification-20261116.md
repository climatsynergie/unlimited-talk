# Optional, lossless qualification — 16 November 2026

Owner explicitly superseded the old mandatory/Canadian-postal validation policy: no qualification question is compulsory, and answers must be saved as entered. This is an intentional policy change, not removal of tests to conceal defects. Work stays in the existing isolated QA worktree based on553c0bb.

## Behavior and data contract

- All qualification questions are optional for draft saving and appointment creation/edit/reconfirmation. Creating an appointment without a questionnaire (omitted ornull) yields an empty supported snapshot. An old appointment can be reconfirmed without inventing answers. Supported historical questionnaire versions can be booked without forcing the latest version.
- Postal codes are ordinary text: no Canadian pattern, case conversion, whitespace removal, separator normalization or guessed corrections. All answer strings, including leading/trailing whitespace, Unicode, newlines, arbitrary option wording and notes longer than2000characters, retain their submitted value.
- Previously conditional answers are never discarded when a parent choice changes. Current question metadata advertises no conditions/required answers. All current questions remain visible, and historical summaries display every stored nonempty answer.
- Standard radio/select options remain shortcuts. **Réponse libre** permits other wording, displays already-saved free text, and **Effacer la réponse** permits clearing an accidental selection. No qualification input has HTMLrequired/pattern/maxLength. Progress describes fields filled, not essentials; stars/mandatory instructions are removed.
- **Enregistrer la qualification** is also available in the inline call sheet, allowing partial information to be explicitly saved without an appointment. Unsaved inline typing still follows the previously requested next-contact behavior; no silent autosave or forced hold is added. Explicit saves use existing immutable events, idempotency, revision conflict and busy/context protection. The keyed per-contact sheet prevents free-input UI state carrying to another client.
- Calendar date/time/timezone/duration remain necessary to create a real calendar slot; qualification can be saved independently of those scheduling fields. Authentication/roles, CSRF/origin, campaign access, opt-outs, actor attribution and concurrency/idempotency are unchanged.

The existing field definitions and stored questionnaire versions1/2/3 remain immutable; current optional-input policy is separated in the API metadata. No migration/version bump or rewrite of historical snapshots occurs. Canonical contact/imported profile data is not overwritten by saving qualification. Structural/schema/type guards and the existing512KiB HTTP limit remain; PostgreSQLJSONB cannot storeNUL, so that technical case is safely rejected with a redacted field-specific error. These are not business format restrictions. `complete` in newly stored event metadata now means accepted by the current optional policy, not every question filled.

## Executed verification

- New policy regression baseline:8methods,1assertion failure/11subtest errors reproduce the old restrictions. Fixed:8methodsPASS.
- Complete backend suite:235PASS.
- Actual HTTP/PostgreSQL shared-calendar suite:PASS. Missing/empty/partial/historical qualification books successfully; arbitrary postal/free-choice/long multiline text persists exactly on draft and appointment reads. Earlier appointment snapshots remain equal. Concurrent writes still yield one409, idempotent retries stay stable, access revocation/role protections, audit immutability, DST/timezone validation and bounded history remain verified. Fresh disposable schema0012 and cleanupPASS; data marker verifiedsynthetic_only before deletion. No production data, real call or external provider was used in these tests.
- Final Chromium surrounding suite:71PASS/0skipped. Empty qualification books, inline partial/free/long-text saves, required/pattern/star absence, legacy free-text display and non-destructive next-contact flows execute alongside incoming callback/history/reception/session and outgoing phone regressions. API/SDK boundaries are synthetic in this local browser suite. Axe WCAG2A/AA and mobile overflow assertions pass in the executed cases.
- TypeScript/production build and formattingPASS. Complete exact-new-source mainCI/image publication/provenance and deployment are pending at this report’s creation.

## Retained failures and requirement updates

The first frontend build failed on an unused event parameter after removing mandatory validity handling; corrected, then built successfully. The first backend full run failed one obsolete trimming assertion; it now asserts the exact leading/trailing spaces required by the owner. The first browser run:30PASS/1FAIL because an older test expected empty qualification to prevent booking. That scenario now verifies scheduling-date admission and still requires the complete filled questionnaire snapshot in its positive branch; a separate new scenario explicitly verifies empty qualification booking. A follow-up surrounding run:70PASS/1FAIL because that changed test tried clicking a deliberately disabled button with no date. It now positively asserts the disabled state/no writes, then fills the date and verifies successful booking. All original logs/traces remain; no failing assertion was silently deleted or weakened to green. Historical-value, invalid-shape, security and conflict assertions remain.

Prior postal-rejection cases were updated to assert raw acceptance per the new requirement; safe-error/privacy checks now use an actual unsupportedNUL fixture. Old mandatory/conditional-deletion/forced-current-schema negatives were replaced by explicit accepted-empty/free/retained-value cases; independent malformed version/unknown-field/type negatives remain.

## Exact commands and evidence

### flexible-qualification-before: FAIL, exit 1

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -e PYTHONDONTWRITEBYTECODE=1 -v /home/codexdev/unlimited-talk-qa-audit/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro unlimited-talk-qa-audit:dependency-hardened python -m unittest discover -s /tests -p test_flexible_qualification.py -v
```

[metadata](evidence/flexible-qualification-before.json), [log](evidence/flexible-qualification-before.log).

### flexible-qualification-after: PASS, exit 0

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -e PYTHONDONTWRITEBYTECODE=1 -v /home/codexdev/unlimited-talk-qa-audit/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro unlimited-talk-qa-audit:dependency-hardened python -m unittest discover -s /tests -p test_flexible_qualification.py -v
```

[metadata](evidence/flexible-qualification-after.json), [log](evidence/flexible-qualification-after.log).

### flexible-qualification-unit: FAIL, exit 1

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -e PYTHONDONTWRITEBYTECODE=1 -v /home/codexdev/unlimited-talk-qa-audit/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro -v /home/codexdev/unlimited-talk-qa-audit/scripts:/scripts:ro unlimited-talk-qa-audit:dependency-hardened python -m unittest discover -s /tests -p 'test_*.py' -v
```

[metadata](evidence/flexible-qualification-unit.json), [log](evidence/flexible-qualification-unit.log).

### flexible-qualification-unit-final: PASS, exit 0

```sh
sudo -n docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges --memory 256m -e PYTHONDONTWRITEBYTECODE=1 -v /home/codexdev/unlimited-talk-qa-audit/backend/app:/app/app:ro -v /home/codexdev/unlimited-talk-qa-audit/tests:/tests:ro -v /home/codexdev/unlimited-talk-qa-audit/scripts:/scripts:ro unlimited-talk-qa-audit:dependency-hardened python -m unittest discover -s /tests -p 'test_*.py' -v
```

[metadata](evidence/flexible-qualification-unit-final.json), [log](evidence/flexible-qualification-unit-final.log).

### flexible-qualification-build: FAIL, exit 1

```sh
npm --prefix frontend run build
```

[metadata](evidence/flexible-qualification-build.json), [log](evidence/flexible-qualification-build.log).

### flexible-qualification-build-styled: PASS, exit 0

```sh
npm --prefix frontend run build
```

[metadata](evidence/flexible-qualification-build-styled.json), [log](evidence/flexible-qualification-build-styled.log).

### flexible-qualification-browser: FAIL, exit 1

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=flexible-qualification npm --prefix frontend run test:browser -- autodialer.spec.ts
```

[metadata](evidence/flexible-qualification-browser.json), [log](evidence/flexible-qualification-browser.log).

### flexible-qualification-browser-final: FAIL, exit 1

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=flexible-qualification-final npm --prefix frontend run test:browser -- autodialer.spec.ts inbound-callback.spec.ts call-history.spec.ts incoming.spec.ts incoming-session.spec.ts phone.spec.ts
```

[metadata](evidence/flexible-qualification-browser-final.json), [log](evidence/flexible-qualification-browser-final.log).

### flexible-qualification-browser-release: PASS, exit 0

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=flexible-qualification-release npm --prefix frontend run test:browser -- autodialer.spec.ts inbound-callback.spec.ts call-history.spec.ts incoming.spec.ts incoming-session.spec.ts phone.spec.ts
```

[metadata](evidence/flexible-qualification-browser-release.json), [log](evidence/flexible-qualification-browser-release.log).

### flexible-calendar-http-postgres: PASS, exit 0

```sh
env 'FOUNDATION_COMPOSE_ARGS=-p ut-flexqual-20261116 -f /home/codexdev/unlimited-talk-qa-audit/compose.yaml -f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/flexible-qualification-20261116/compose.qa.yaml' FOUNDATION_TEST_URL=http://127.0.0.1:18314 python3 tests/verify_calendar.py
```

[metadata](evidence/flexible-calendar-http-postgres.json), [log](evidence/flexible-calendar-http-postgres.log).

### flexible-qualification-format: PASS, exit 0

```sh
npm --prefix frontend run format:check
```

[metadata](evidence/flexible-qualification-format.json), [log](evidence/flexible-qualification-format.log).

### flexible-lab-cleanup: PASS, exit 0

```sh
sudo -n docker compose --project-directory /home/codexdev/unlimited-talk-qa-audit -p ut-flexqual-20261116 -f compose.yaml -f qa-reports/evidence/flexible-qualification-20261116/compose.qa.yaml down --volumes --remove-orphans
```

[metadata](evidence/flexible-lab-cleanup.json), [log](evidence/flexible-lab-cleanup.log).

## Limits

No valid booking/draft was written to production by the tools. Real carrier/headset acceptance and live human entry are NOT TESTED; broad production certification is not inferred. An application rollback to the preceding release would restore its stricter editing policy while leaving the stored JSON/history intact; forward deployment restores the new policy without a data migration.

## Follow-up: legacy reconfirmation gate aligned with the owner’s new policy

Main CI43781860958 for3f9589c stopped at `Verify reconfirmation authorization and callback handoff regressions`; publication was skipped and nothing from that run was deployed. The legacy security suite still asserted422 for a cancelled/completed/no-show appointment without qualification. The same suite was executed locally against the new application:14methods,3subtest failures reproduce the old422-versus-new200 expectation. Its updated scenario now positively verifies successful booked status/version increment, empty supported snapshot, correct pipeline synchronization, one immutable before/after event and retained original status for all three prior statuses. All surrounding authorization, opt-out, archived/unassigned campaign, concurrency, historical-note and due-callback/English-handoff assertions remain intact. No application code changed in this follow-up. The complete real HTTP/PG suite then passed14methods. Raw local and CI failure evidence is retained.

### flexible-reconfirmation-old-policy: FAIL, exit 1

```sh
env 'FOUNDATION_COMPOSE_ARGS=-p ut-qa-flexqual-20261116 -f /home/codexdev/unlimited-talk-qa-audit/compose.yaml -f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/flexible-qualification-20261116/compose.qa.yaml' python3 tests/verify_backend_reconfirmation.py
```

[metadata](evidence/flexible-reconfirmation-old-policy.json), [log](evidence/flexible-reconfirmation-old-policy.log).

### flexible-reconfirmation-new-policy: PASS, exit 0

```sh
env 'FOUNDATION_COMPOSE_ARGS=-p ut-qa-flexqual-20261116 -f /home/codexdev/unlimited-talk-qa-audit/compose.yaml -f /home/codexdev/unlimited-talk-qa-audit/qa-reports/evidence/flexible-qualification-20261116/compose.qa.yaml' python3 tests/verify_backend_reconfirmation.py
```

[metadata](evidence/flexible-reconfirmation-new-policy.json), [log](evidence/flexible-reconfirmation-new-policy.log).


## Follow-up: browser reconfirmation regression aligned with optional policy

Main CI43782834707 for2ea00fc stopped at the HTTPS browser gate; no image was published or deployed. Its three browser scenarios still expected an empty legacy qualification to block saving. Local execution reproduced all three obsolete expectations (exit1). The replacement matrix verifies empty **and** filled qualification for each cancelled/completed/no-show reconfirmation, with exactly one PATCH, the correct supported schema/answers, zero required qualification inputs and no unexpected requests. The legacy fixture deliberately retains `required: true` metadata, proving the current interface applies the requested optional policy even to older snapshots. No application behavior changed in this follow-up. All six browser scenarios passed.

### flexible-calendar-browser-old-policy: FAIL, exit1

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=flex-calendar-old npm --prefix frontend run test:browser -- calendar-reconfirmation.spec.ts
```

[metadata](evidence/flexible-calendar-browser-old-policy.json), [log](evidence/flexible-calendar-browser-old-policy.log).

### flexible-calendar-browser-new-policy: PASS, exit0, six tests

```sh
env UI_TEST_URL=http://127.0.0.1:15174 QA_EVIDENCE_MODE=flex-calendar-new npm --prefix frontend run test:browser -- calendar-reconfirmation.spec.ts
```

[metadata](evidence/flexible-calendar-browser-new-policy.json), [log](evidence/flexible-calendar-browser-new-policy.log).

## Final release verification — 16 November2026,01:33UTC

**DEPLOYED / PASS within this change’s scope.** Live source `0e18ba6c5fe7e7b1db433922df518ed5cfb58618`, immutable image `ghcr.io/climatsynergie/unlimited-talk-api@sha256:e1803fd25bae1a3bd95fa83cff2f1909c01fbabf22e9202228150051beca462c`. Main CI[43784893313](https://github.com/climatsynergie/unlimited-talk/actions/runs/43784893313) and QA CI[43784893424](https://github.com/climatsynergie/unlimited-talk/actions/runs/43784893424) both completed successfully. Main published the exact tested image and its attestation. Existing unit/API/calendar/telephony/security/browser/schema/rollback/recovery gates were retained. No preceding release was substituted for this candidate’s validation.

Local focused evidence:235 backend unit tests,71 affected phone/incoming/dialer/history browser tests plus6 legacy reconfirmation browser cases,14 real HTTP/PostgreSQL reconfirmation methods and the dedicated calendar HTTP/PostgreSQL assertions; commands/exits are recorded above. Full CI additionally passed the HTTPS browser, actual browser→API→PostgreSQL agent/incoming workflows, schema/rollback/restore/outage and incoming-runtime suites. A single combined test count is not invented for script-style suites.

Root deployment used the unchanged reviewed deployer with its installed-code hash check, exact current main/successful CI/image/source/schema/provenance gates, exclusive deployment lock, idle-call checks and calling-preservation/rollback context. Only public artifact/API authentication transport was adapted for this owner-authorized root invocation. Previous release553c0bb remains the normal rollback target; no active-call protection was bypassed. Calling resumed successfully. No valid live appointment/qualification was submitted by QA tools.

Post-deploy probes confirmed all seven services running, six configured healthchecks healthy, no OOM, exact image/source, schema0012, manual mode and calling enabled. The installed model accepts empty qualification, arbitrary postal/free-choice text and long comments without alteration. Read-only optimized queue probes completed in24.24ms and13.89ms with the expected index/defaults. Public checks verified delivered new bundle/routes, technical invalid-NUL rejection with redacted feedback, unauthenticated calendar denial and hidden operations endpoints. Those invalid probes do **not** write real records or reinstate postal formatting rules.

One premature `flexible-qualification-ci-approved` gate check exited1 while main publication was still in progress. It did not deploy anything and is retained as FAIL/incomplete gate evidence. The later `flexible-qualification-ci-final` gate exited0 only after both runs and publication completed successfully.

### flexible-qualification-ci-approved: FAIL, exit 1

```sh
python3 qa-reports/evidence/flexible-qualification-release/check_ci.py --require-complete
```

[metadata](evidence/flexible-qualification-ci-approved.json), [log](evidence/flexible-qualification-ci-approved.log).

### flexible-qualification-ci-final: PASS, exit 0

```sh
python3 qa-reports/evidence/flexible-qualification-release/check_ci.py --require-complete
```

[metadata](evidence/flexible-qualification-ci-final.json), [log](evidence/flexible-qualification-ci-final.log).

### flexible-qualification-image-provenance: PASS, exit 0

```sh
ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 /root/prepare-release-0e18ba6.py
```

[metadata](evidence/flexible-qualification-image-provenance.json), [log](evidence/flexible-qualification-image-provenance.log).

### flexible-qualification-deployment: PASS, exit 0

```sh
ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 /root/deploy-release-0e18ba6.py
```

[metadata](evidence/flexible-qualification-deployment.json), [log](evidence/flexible-qualification-deployment.log).

### flexible-qualification-runtime-final: PASS, exit 0

```sh
ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 /root/verify-runtime-release-0e18ba6.py
```

[metadata](evidence/flexible-qualification-runtime-final.json), [log](evidence/flexible-qualification-runtime-final.log).

### flexible-qualification-public-final: PASS, exit 0

```sh
python3 qa-reports/evidence/flexible-qualification-release/verify_public.py
```

[metadata](evidence/flexible-qualification-public-final.json), [log](evidence/flexible-qualification-public-final.log).

Real17-agent headset/PSTN/media acceptance remains **NOT TESTED**, separate from the successful optional-form release and20-agent synthetic admission experiment. See [capacity assessment](seventeen-agent-readiness-20261116.md). No unconditional whole-application production certification is inferred.
