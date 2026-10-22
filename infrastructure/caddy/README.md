# Staging HTTPS perimeter

Install Caddy from its official stable Debian/Ubuntu repository, running its
packaged systemd service. This host service terminates HTTPS and proxies only
to the existing loopback gateway. It is independent of application releases.

Install `Caddyfile` at `/etc/caddy/Caddyfile` and `staging.conf` at
`/etc/systemd/system/caddy.service.d/staging.conf` (root-owned, mode 0644).
Create `/etc/caddy/staging.env` (root-owned, mode 0600) with the actual
`STAGING_DOMAIN=...`. Never put real credentials in this repository.

Create `/etc/caddy/staging-access.caddy` (root:caddy, mode 0640):

```caddyfile
basic_auth {
    staging REPLACE_WITH_BCRYPT_HASH
}
```

Generate a unique random password, keep it in the team's password manager and
hash it using `caddy hash-password` over stdin. Do not supply passwords as CLI
arguments or log their contents. Keep any server recovery copy root-only.
The perimeter account protects all application routes, including OpenAPI and
health endpoints; it is not an application admin account or a substitute for
application authentication, roles, audit history or individual access control.
This dedicated Authorization header is removed before proxying. When application
bearer authentication is introduced, revise the perimeter integration explicitly
(e.g. identity-aware access) rather than passing its password to the backend.

Validate the configuration with STAGING_DOMAIN set, then daemon-reload and
restart Caddy. Allow inbound TCP 80/443 in host and provider firewalls; the
application gateway must stay loopback-only and PostgreSQL private. Caddy
persists certificates under its service data directory and renews automatically.
Do not copy certificate private keys into Git or application images.

Verify from outside the server: HTTP redirects to HTTPS, a trusted certificate
matches the domain, unauthenticated root/docs/readiness requests return 401,
invalid credentials return 401, and authenticated readiness returns the expected
revision and connected database. Confirm reboot startup is enabled and inspect
`journalctl -u caddy` for issuance/renewal errors. Do not use `curl -k` as an
acceptance check. No access logging is enabled by this template.

On the configured staging host, `/root/staging-web-access.py` displays the
root-only recovery credential for direct transfer into a password manager.
Never paste that output into chat, GitHub or deployment logs. Credential
rotation requires replacing the bcrypt hash and reloading validated Caddy
configuration; deleting a browser session alone does not revoke Basic access.
