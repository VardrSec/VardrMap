# Local accounts alongside GitHub

Set `VARDRMAP_AUTH_METHODS` to `github` (default), `local`, or `github,local` in
both backend and frontend configuration. Invalid or empty values fail closed.
This selects authentication methods; it does not select a different backend or
disable application permissions. API keys remain supported independently.

Install backend requirements and apply migrations through the existing migration
procedure. `0031localauth` creates three new tables without renaming existing user
IDs or transferring ownership. Keep a verified backup before any real upgrade.
Automatic downgrade across this revision is refused because it would delete
credentials/sessions; use a separately reviewed restore/recovery procedure.
Roll out the backend before the browser changes: the login screen requires the
new `/auth/methods` endpoint, including in GitHub-only mode. Match authentication
configuration on both services and build the UI with its intended API URL.

## First local administrator

In the backend environment, run:

```sh
python -m local_accounts init --username operator
```

Enter and confirm a 15–128-character password/passphrase without terminal echo.
Alternatively add `--generate-password` to generate/display one password in that
terminal; store it securely. Password arguments are not accepted, preventing
placement in shell history. Bootstrap is one-time and transactional: concurrent
attempts cannot create multiple initial accounts. No default password, public
bootstrap route, registration endpoint or startup bootstrap is provided.

The account owns its personal organization/workspace. It is not a global superuser
and cannot access existing GitHub-owned engagements without the existing grants.
The first slice manages one initial local account; account invitations/linking or
additional local-account administration require separate implementation.

## HTTPS, sessions and CSRF

Serve both UI and API over HTTPS, configure the UI's HTTPS `NEXT_PUBLIC_API_URL`,
and put the exact UI origin in backend `ALLOWED_ORIGINS`. Configure certificate
trust and trusted reverse-proxy handling deliberately. Do not disable TLS checks
or trust arbitrary forwarded headers. The browser UI must not send local passwords
to an HTTP URL. Local sessions are always secure; no localhost exception exists.
Keep UI and API on the same HTTPS site (one hostname with separate ports, a
same-site API subdomain, or a reverse proxy). `SameSite=Lax` deliberately does not
support unrelated UI/API sites. GitHub's bearer transport remains available for
existing hosted deployments with separate sites.

Passwords use Argon2id at 64 MiB, time cost 3, parallelism 4. Budget memory for
concurrent checks. Login is limited to ten requests/minute per client IP; five
wrong attempts lock a known account for 15 minutes. Failures use a generic response
and unknown/locked users undergo dummy hash verification. Configure trusted proxy
IP forwarding so this limit observes the actual client rather than a shared proxy.

Session tokens are random and only their SHA-256 digests are stored. The raw token
appears only in a host-only `__Host-` secure HTTP-only cookie. Sessions expire after
eight hours absolutely or 30 minutes idle; requests do not extend the absolute
deadline. Login rotates the token. Logout revokes it; password changes and terminal
recovery revoke the user's other/all local browser sessions respectively.

Concurrent login, password change and recovery serialize on the credential row.
Keep verification and session issuance in that transaction: moving password work
outside the lock requires revalidating the credential before issuing a session.
PostgreSQL tests cover simultaneous failures, recovery waiting on an in-flight
login, competing password changes and revocation during the activity refresh.
That refresh returns unauthorized if revocation deleted its row. A request already
authorized before revocation may finish; revocation does not cancel in-flight work.

Fetch the authenticated session metadata to obtain `csrfToken`. All cookie-based
writes, including existing application endpoints, must send that value as
`X-CSRF-Token` and an explicitly allowed Origin. Login also requires an allowed
Origin. SameSite/CORS are additional controls, not the only CSRF protection.
Bearer JWT/API-key callers keep their existing transport and authorization flow.
GitHub JWTs cannot impersonate the reserved local user-ID namespace.

## Recovery and credential lifecycle

With explicit access to the backend environment:

```sh
python -m local_accounts reset-password --username operator
```

This reads a replacement password without echo and revokes all local browser
sessions. It does not create another account or change ownership. Existing API
keys remain separate credentials; revoke them through their existing management
flow when required. Protect backend/database access and backups, which include
password hashes and session digests. No production passwords or credentials belong in
configuration examples, logs, test fixtures or source control.

The login screen shows the explicitly enabled methods. Sign in locally with the
initial account, manage its password in Settings, and use Sign out to revoke the
server session. Reloads retain a valid local session without exposing a bearer
token to JavaScript; expiry returns the browser to sign-in on the next API request.
Existing GitHub deployments retain their provider and API behavior by default.
No deployment, image publication or release is performed by these changes.
