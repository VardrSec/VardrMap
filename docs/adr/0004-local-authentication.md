# ADR 0004: Add local identities and revocable cookie sessions

Status: Accepted, 2026-10-25. Local authentication is opt-in and not yet released.

## Decision

Use explicit `VARDRMAP_AUTH_METHODS=github`, `local`, or `github,local` configuration.
Default to GitHub, retain its OAuth/Auth.js flow and existing API-key support, and
reject unknown/empty method settings. Keep one backend and the same authorization
dependencies, users, organizations, ownership and permission predicates.

Preserve the legacy `users.github_id` primary key and related ownership columns.
Local identities use reserved `local:<uuid>` values and a separate local-credentials
table. GitHub-issued JWTs cannot identify a reserved local user. Bootstrap creates
the owner of a personal organization, not a superuser who can bypass tenant checks.

Bootstrap is an explicit server-terminal operation. A transactionally unique
singleton claim and account/org creation commit together. There is no anonymous
HTTP account-creation route and no default/shared password. Read the initial
password without echo or explicitly generate/display one in that terminal.
Recovery is likewise an explicit server operation; neither flow runs at startup.

Store Argon2id hashes with 64 MiB memory, time cost 3 and parallelism 4. Accept
15–128 characters, including spaces and Unicode; reject whitespace-only values.
Use generic login failures and dummy verification for unknown/locked users. Limit
login attempts per client IP and persist a 15-minute account lock after five
failures; successful login resets the counter and upgrades hash parameters when
needed. Do not require an external password-checking service for local operation.

Local sessions use random 256-bit tokens, with only SHA-256 token digests stored.
Send the raw token only in a host-only `Secure`, `HttpOnly`, `SameSite=Lax` cookie
with `Path=/` and the `__Host-` prefix. Local authentication requires HTTPS, even
on localhost. Sessions have an eight-hour absolute limit and 30-minute idle limit.
Rotate on login/password change; logout, recovery and password changes revoke
server-side sessions. Password changes require the current password.

Every cookie-authenticated write must have an explicitly allowed Origin and a
session-bound HMAC CSRF token returned through the authenticated session endpoint.
Login also requires an allowed Origin and JSON; CORS, SameSite and content type
are additional protections rather than substitutes for CSRF validation. Cookie
authentication resolves through the existing permission checks. Bearer/API-key
requests retain their existing behavior and do not fall back to a cookie on error.

Local login/session responses never return a bearer/session secret in JSON. The
frontend will adapt its shared request helper for cookie credentials and CSRF,
while existing GitHub bearer requests remain supported. Local auth responses are
not cached; validation failures must not echo submitted passwords.

## Consequences

Add three tables and the Argon2 dependency without modifying existing users or
ownership. The migration upgrade is additive. Automatic downgrade is refused
because it would delete credentials and sessions; recovery requires a verified
backup and a separately reviewed procedure. Previous feature roundtrip tests
remain scoped to their revisions; test this new refusal and data preservation.

Authentication is separate from deployment mode. Enabling local does not disable
authorization, turn existing API keys into cookies, create a scan worker, or
publish/deploy anything. This first local flow supports the initial account;
additional local-account administration and account linking need separate review.
Existing API keys remain separate credentials with their existing revocation flow.

The UI and API must use HTTPS with correctly configured origins/certificate trust.
Use trusted proxy handling for TLS termination; never trust arbitrary forwarded
headers to bypass the transport check. Deployment must budget Argon2 memory and
configure trusted-proxy rate-limit addressing. Local sessions do not replace or
weaken the hosted GitHub flow.

References: [Argon2-cffi](https://argon2-cffi.readthedocs.io/en/stable/howto.html),
[OWASP authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html),
[OWASP CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).
