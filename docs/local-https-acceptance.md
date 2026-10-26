# Local HTTPS: required Community release acceptance

Status: distribution release gate; the trusted first-install experience is not yet
implemented. Map's HTTPS browser fixture verifies authentication with a disposable
certificate, not certificate trust installation. It must not be used as evidence
that a fresh user can complete a one-command installation.

The distribution must provide one documented HTTPS entry point for UI and API,
with same-site routing, matching authentication configuration and a migrated
database. A local reverse proxy with a persistent installation-specific CA is the
preferred design for evaluation. An installer must explain and explicitly perform
any required trust enrollment; starting Compose alone cannot be represented as
silently establishing browser trust. Never distribute a shared CA private key.

Required acceptance on each supported operating system:

1. Begin with a clean browser profile and no pretrusted fixture certificates.
   Follow only the shipped install instructions, including an explicit trust step
   if required. Open the documented URL without certificate warnings.
2. Complete migrations and terminal bootstrap, then sign in through the real UI.
   Keep HTTPS required, certificate validation enabled, Secure/HTTP-only cookies,
   Origin/CSRF checks and existing organization permissions.
3. Verify the API and Runner validate the same intended certificate chain through
   documented trust configuration. Confirm untrusted certificates fail; no
   `ignoreHTTPSErrors`, `--insecure` or global TLS-verification bypass is permitted.
4. Keep database/backend management ports private or loopback-bound. Trust forwarded
   scheme/client-IP headers only from the configured proxy, and verify direct
   untrusted callers cannot spoof them.
5. Exercise restart, stop/start, update and certificate renewal with persistent
   data/trust material; confirm login still works and stale sessions stay revoked.
6. Verify missing trust, stopped components and incomplete backend upgrades give
   actionable diagnosis through Runner and login recovery guidance.
7. Document CA/private-key protection, backup/recovery, removal and trust cleanup.
   Demonstrate these steps before claiming a complete Community installation.

These checks belong to VardrSec distribution acceptance. They are separate from
Map's current browser tests and must pass before a Community release advertises
one-entry-point installation. No certificate is installed into the user's trust
store by the Map tests or by these documentation changes.
