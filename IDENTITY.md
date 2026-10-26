# Identity backend

The server API is used by the React login/admin screens described in WEB.md.
Automatic email delivery is not implemented. Public access still passes through the independent staging
HTTPS password perimeter. Business endpoints must use the shared `authenticate`
or `admin` guard and enforce their own campaign/contact/appointment permissions.
Having an agent role alone does not grant access to future business records.

## Accounts and permissions

There is no public registration/bootstrap endpoint. An administrator creates a
24-hour invitation for a normalized email, display name and explicit admin/agent
role. The token is returned once for direct delivery over an approved private
channel; invitation listings contain no tokens. Creating a replacement revokes
its predecessor. Acceptance and account creation commit atomically; expired,
revoked and previously accepted invitations fail.

Agents can read their own identity, change their password, sign out, or revoke
all their sessions. Admins can additionally list users, issue/revoke invitations,
change roles/active status, revoke another user's sessions, issue password-reset
tokens and read the audit journal. Admin actions that change data require a
session authenticated within the last 15 minutes. Role changes/deactivation
revoke every session of the affected user. The last active, MFA-enrolled admin
cannot be deactivated or demoted, including concurrent administrative requests.

## Browser contract

The browser API lives under `/api/auth` and `/api/admin`. Use JSON bodies with
`credentials: 'same-origin'`. Every unsafe request, including login and invitation
acceptance, must carry an `Origin` exactly matching configured `APP_ORIGIN`.
For authenticated writes, also send `X-CSRF-Token` equal to the readable
`__Host-ut_csrf` cookie. The server verifies it against the stored session hash.
No cross-origin API access or permissive CORS is enabled.

The opaque session is a 256-bit random value in a `Secure`, `HttpOnly`,
`SameSite=Strict`, host-only cookie. CSRF uses a distinct random value. Only
SHA-256 hashes of these random tokens are stored in PostgreSQL. Session values
are never returned in JSON or stored in browser localStorage. Lifetimes are
12 hours absolute and 30 minutes idle, checked by the database on every request.
Admin MFA enrollment sessions last only 10 minutes and cannot access admin
operations until confirmation. Login, password changes and MFA confirmation
rotate cookies. Logout/revocation is durable across application restarts.

Passwords use Argon2id (64 MiB, three iterations, one lane), random salts and
constant-time library verification. Passwords support 12–128 characters without
composition rules; a small local weak-password check is not a comprehensive
breached-password corpus. Two concurrent hash workers bound memory usage.
Database counters throttle login, enrollment, invitation acceptance, password
changes and recovery: ten attempts per identity/operation per 15 minutes, plus a
shared 200-per-minute ceiling. These counters survive process restarts. This
protects staging; evaluate rate budgets/load and a dedicated edge limiter before
production exposure. Do not trust arbitrary forwarded headers as client identity.

## MFA and recovery

Admins must enroll a TOTP authenticator before obtaining admin access. TOTP
uses PyOTP, a 30-second interval and a one-step clock tolerance. A row lock and
last accepted counter prevent concurrent replay. Eight 192-bit random recovery
codes are shown once; only hashes persist and each code can be consumed once.
Using one requires the account password. MFA seeds are encrypted using Fernet
with a separate API-only file secret. Recovery/password reset never bypasses an
existing MFA factor. TOTP is not phishing-resistant; hardware-backed WebAuthn is
an additional future security option, not a capability delivered here.

Admins can issue a 30-minute, one-use password-reset token for an active user.
Issuance and completion revoke that user's sessions. The user chooses the new
password; admins never set or retrieve it. A replacement token revokes previous
ones. Send the token privately; do not embed secrets in URL paths/query strings
or paste them into chat/logs. The invitation/reset screens use a URL fragment removed immediately on load
and keep the token only in transient page memory. No automated email
or self-service email recovery is implemented.

If both the authenticator and all recovery codes are lost, controlled operator
recovery is required; there is no public MFA bypass/reset endpoint.

## First administrator and host preparation

First deploy the already verified compatibility release identified in DELIVERY.
An operator installs the reviewed managed Compose template and deployer, creates
`/etc/unlimited-talk-staging/identity-config.json` with the HTTPS `origin`, and
provisions a unique Fernet key at
`/etc/unlimited-talk-staging/container-secrets/identity_key`. The key is owned by
UID 10001, mode 0400, inside the root-only container-secrets directory; it is
mounted only in the API. Never overwrite it during deployment or put it in Git,
GitHub Actions secrets, `.env`, logs or chat. Migrations do not receive the key.

After identity deployment passes readiness, use the staging Web Console:

```sh
python3 /root/bootstrap-staging-admin.py
```

This runs `python -m app.identity.bootstrap` interactively inside the deployed
API. Enter the email/name, choose and confirm a hidden password, add the displayed
MFA seed to your authenticator, confirm its code and store the recovery codes in
a password manager. There is no default password. Bootstrap refuses once any
user exists and serializes the final database check to prevent a second first
admin. The just-confirmed TOTP cannot be reused for login; wait for a new code.
Do not run this through CI/noninteractive logs. No real account is created by
installation or by the synthetic tests.

Back up the encryption key independently with restricted access before valuable
accounts/data are admitted, and exercise restoration with PostgreSQL backups.
Losing it makes existing MFA seeds unreadable. Rotation requires an explicit
reencryption/multi-key rollout; generating a replacement file is not rotation.
Readiness checks the schema, all identity tables and decryptability of an existing
MFA seed, so an accidentally replaced key prevents a healthy deployment.

## Audit and validation

Successful identity/security changes and failed logins append an audit event in
the same transaction. Events contain actor/subject identifiers and fixed action
names, not passwords, tokens, OTPs or MFA seeds. The runtime may insert/read but
cannot update/delete/truncate audit rows or delete users. This is an application
permission boundary, not tamper-proof storage against the database administrator.
Sensitive validation inputs and SQL parameters are omitted from error output;
request logs exclude query strings and bodies.

CI uses disposable PostgreSQL and synthetic accounts to verify role denial,
last-admin protection, CSRF/origin enforcement, cookie properties/rotation,
invitation expiry/revocation/concurrent acceptance, MFA enrollment/replay/recovery,
password changes/reset without MFA bypass, immediate revocation/deactivation, session expiry,
throttling, incorrect-key readiness failure and audit permissions. It switches to the exact preceding application
image against the real migrated schema, verifies identity data preservation, then
restores the new app. No automatic downgrade or deletion of identity data exists.
A green local/CI test is not proof of a completed managed staging deployment;
verify the deployed revision and HTTPS/API flow before calling it activated.
