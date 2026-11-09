# Native image refresh — validation in progress

Production release: **NO-GO**. This candidate is confined to the QA branch; no deployment, main merge or real call is authorized or performed.

Updated compatible digest pins: CPython 3.12.16/Alpine3.24.4; Node22.23.4/Alpine3.24.4; Redis8.2.11/Alpine3.22.8; PostgreSQL18.6/Alpine3.24.4; upstream Nginx unprivileged1.30.6 slim in the official `nginx/nginx-unprivileged` namespace. The slim image omits optional modules unused by the production gateway configuration. Actual runtime compatibility must pass tests before acceptance.

Fresh registry layers were streamed and checked against their digest. Fresh Alpine security databases were compared with extracted APK inventories. This is package provenance/version evidence, not proof of end-to-end behavior or complete native security coverage. Exact commands, hashes, timestamps and raw inventories are retained locally under `evidence/native-refresh/`.

Confirmed residual blockers: official CPython3.12.16 statically bundles Expat2.9.0, preceding the2.10 security fixes; psycopg-binary3.3.6 statically ships its own OpenSSL3.5.7, which APK upgrades do not replace. The latest compatible3.3.8 wheel also embeds3.5.7; a blind dependency bump does not fix it. The HIGH DTLS advisory's reachability through libpq's TCP/TLS path has not been established. Narrow reachability/component assessments are documented separately.

Fresh clean local Dockerfile build: **FAIL**, actual no-space-left-on-device during runtime dependency-layer commit. The failure log is preserved. Only unused build cache has been reclaimed; production resources and synthetic database volumes remain intact. A new QA-branch clean CI build is required; the preceding source's successful CI cannot validate these new pins.

Fresh backend/browser/database checks: **NOT TESTED** for the new candidate until executed. Real carrier/headset/agent acceptance: **BLOCKED**, pending explicit authorization, appropriate credentials and participants. Live warm/blind audio transfer: **BLOCKED — not implemented**; English contact handoff is not an audio transfer.
