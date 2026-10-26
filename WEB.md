# Identity web application

The React/TypeScript application uses Vite to build static, versioned assets.
A pinned Node 22 build stage runs `npm ci` from the committed lockfile, checks
TypeScript and bundles the app. Only `dist` is copied into the Python runtime;
no Node server, dependency directory or frontend source is shipped at runtime.
FastAPI serves the HTML and static assets through the existing gateway/Caddy
chain. All identity requests use the same origin; there is no public API key,
frontend secret, third-party font, analytics script or cross-origin API setting.

## Screens

- Connection with email, password and an optional Authenticator/recovery code.
- Invitation acceptance and password reset from a one-use private link.
- Required admin MFA enrollment with a locally generated QR code, manual key
  fallback, confirmation and one-time recovery-code acknowledgement.
- Agent welcome page and account/security settings for both roles.
- Admin users list with server-side search, pagination, role/status changes,
  session revocation and password-reset link creation.
- Invitation creation, status/expiration, pagination and explicit revocation.
- Read-only audit journal with actor/subject labels and cursor pagination.

Sensitive account actions open a confirmation dialog. Failure does not appear as
success; server messages explain an expired session, insufficient permissions,
last-admin protection, a stale reauthentication or a failed save. Native modal
dialogs manage focus and Escape; Escape/close is blocked while a mutation is in
flight. A reconnect action allows fresh password/MFA verification when needed.

Agents do not see admin navigation; API authorization remains authoritative.
There are no simulated contacts, campaigns, calls, appointments or metrics.

## Browser security and navigation

`/` and the explicit connection/account/admin paths serve the application HTML.
Unknown API routes still return JSON 404 responses, never the application shell.
`/api/system` retains the non-sensitive foundation metadata previously at `/`.
HTML/identity responses are not cached; content-hashed `/assets` files are cached
immutably. The HTML policy permits only same-origin scripts/styles/connections,
plus local QR image data; it blocks inline/eval scripts, embedding, object content
and external form targets. Referrers are suppressed.

Invitation/reset secrets use fragments, not URL query parameters or paths. The
fragment is removed with `replaceState` before API requests. Generated links are
shown only in the result dialog; closing it discards the displayed value. The
application does not store credentials/tokens/codes in localStorage or
sessionStorage and never saves authenticated browser state or prints secrets.
Reopening the original private link is necessary after refreshing its form.
Recovery codes are shown once; refreshing after enrollment cannot retrieve them.

Session/CSRF cookies follow IDENTITY.md. Logout clears the authenticated UI only
after server acknowledgement (or an explicit expired-session response). A
BroadcastChannel synchronizes logout between tabs without transmitting secrets;
returning to a visible tab rechecks the session. There is no idle polling that
would keep inactive sessions alive. Aborted requests cannot replace current UI
state or terminate a newer session. Failed login requests do not pretend that an
existing session has expired. All important actions use server validation.

## First real login

After a successful signed-image deployment and readiness check, the administrator
uses the staging Web Console to run:

```sh
python3 /root/bootstrap-staging-admin.py
```

Enter the individual email/name, choose the hidden password and confirm it, add
the displayed key to an Authenticator, confirm its current code and securely save
the recovery codes. This command refuses a second bootstrap once a user exists.
Wait for a new authenticator code after bootstrap because the confirmation code
has already been consumed. Open the staging HTTPS address, pass the independent
staging perimeter password, and sign in using the newly created individual
account. No default account/password or public bootstrap page exists.

Admins use “Inviter un membre”, select Agent/Administrateur, then send the
resulting private link directly to its recipient. No email is sent automatically.
Administrators invited this way enroll MFA in the browser before obtaining admin
access. Each user manages their own password and recovery codes.

## Verification and development

Local backend development still uses the built Compose image. Rebuild after UI
changes; TypeScript/format checks can be run with host Node 22:

```sh
npm ci --prefix frontend --ignore-scripts --no-audit --no-fund
npm run --prefix frontend format:check
npm run --prefix frontend build
```

After starting the disposable local Compose database/API, run:

```sh
cd frontend
npx playwright install --with-deps chromium
cd ..
python3 tests/verify_browser.py
```

The browser harness refuses managed deployments, creates an ephemeral loopback
HTTPS proxy/certificate and temporarily sets the disposable API's allowed origin
to `https://localhost:18443`. That exact HTTPS origin is accepted only by local
configuration; managed configuration still requires its configured HTTPS origin.
Real browser cookies, CSRF/origin checks and PostgreSQL writes are exercised.
Ignoring the ephemeral self-signed certificate is confined to Playwright; it is
not a production TLS verification check. The original API configuration is
restored in a `finally` block.

Tests use fresh synthetic identities and cover complete admin invitation → agent
acceptance → account password change → admin password reset → agent recovery →
deactivation; role denial; admin QR/MFA enrollment and recovery-code login;
session expiration; fragment removal/no token in network URLs; secure cookies
and no credential storage; desktop/mobile layouts; HTML/static/404 boundaries;
and axe WCAG A/AA checks on login, admin and agent pages. Traces, failure
screenshots, video and persisted auth state are disabled to avoid secret capture.
Optional local screenshots are limited to synthetic login/admin views. Synthetic
fixture helpers explicitly refuse managed database configuration.

CI verifies that Chromium actually starts before attempting to install missing
system libraries, avoiding unnecessary package-manager updates on prepared
runners. CI runs the full tests before rollback/outage checks and publishes only the tested
image. The preceding identity backend image is used to verify rollback preserves
accounts and migration state. A successful build is not proof of managed staging
activation; verify the deployed revision and real HTTPS screens after dispatching
the manual deployment. Business workflows remain separate milestones.
