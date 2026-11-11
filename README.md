# VardrMap

A platform for authorized security assessments. Organize engagements, record
scope and written authorization, review API cases, coordinate explicitly approved
work, inspect evidence and produce findings and reports.

Map is the research and coordination interface, not the scanning engine.
[VardrRunner](https://github.com/VardrSec/VardrRunner) executes tools locally and
[VardrGate](https://github.com/VardrSec/VardrGate) evaluates declared API
access-control expectations.

## Get started

For the source-built local platform, follow the [VardrSec installation guide](https://github.com/VardrSec/VardrSec/blob/main/docs/installation.md).
This is the **Full** path. It supplies the compatible components, PostgreSQL, local HTTPS, account bootstrap
and lifecycle commands. Starting services does not start scans. Source-built
compatibility does not mean that a Community release has been published.

For a CLI-only installation without Map or PostgreSQL, follow the distribution’s
[Mapless workflow](https://github.com/VardrSec/VardrSec/blob/main/docs/mapless.md).
Full and Mapless have separate state and identities; choosing Mapless is not a
migration of a Full installation. The native commands below are for developing
Map itself, not an alternative Community installation walkthrough.

## Capabilities

- Engagements for penetration testing, bug bounty, red-team and internal work;
  clients, written authorization, testing windows, scope and organization access.
- Asset relationships, recon imports, reviewed API Surface operations and selected
  Burp exchanges. Passive collection remains off.
- Reviewed multi-identity Gate cases, operation/identity/boundary coverage and
  evidence-backed drafts. Credentials are references resolved locally by Runner.
- Explicit jobs and pipelines, status and events, platform diagnostics and
  operator-reviewed AI queue proposals. A pending proposal creates no execution right.
- Findings, retests, redacted evidence, reports and immutable client-deliverable
  revisions. Historical or missing provenance is reported as unknown.

A completed job is not a conclusive assessment; a conclusive assessment does not
prove an API secure. Unsupported and inconclusive cases remain distinct.

<a id="scope-is-advisory"></a>

## Authorization and execution

Legacy/manual workflows retain advisory scope and testing-window warnings.
Those warnings alone do not prevent an operator from sending traffic. Stop-work
blocks new execution; its legacy policy check alone cannot terminate a local
process that is already running.

The supported controlled managed path separately enforces signed authorization,
issuer/origin/job binding, credential grants, expiry and execution budgets.
Managed Full setup and per-job approval are explicit. Existing manual commands
are not silently converted into that mode. Follow the distribution's
[managed setup guide](https://github.com/VardrSec/VardrSec/blob/main/docs/local-managed-setup.md).

Active cancellation depends on the controlled Runner and its documented bounds.
Do not assume instantaneous remote stop during disconnection, or qualified
execution across host suspend/resume. Preserve uncertain results and reconcile
the original run; never replay unknown execution to clear a status.

## Security boundaries

Configured local sessions, browser JWTs and personal API keys share ownership and
organization checks. Inaccessible objects return 404; viewers cannot write.
Local sessions use Argon2id passwords, secure HTTP-only cookies, server-side
revocation, Origin checks and CSRF protection on cookie-authenticated writes.
JWTs require signature, audience, issuer and expiry validation. API keys are
stored as hashes rather than plaintext.

Evidence is redacted on write. Do not submit real credentials in test cases,
reports, issue discussions or AI prompts. Target responses and imported output
are untrusted data. AI tools do not have authority to approve their own work,
change scope or bypass the operator's permissions.

Notifications require validated HTTPS destinations, address checks and disabled
redirects. Read the [security model](docs/security-model.md) and
[local authentication guide](docs/local-authentication.md) for details and limits.
No security control here is a promise of immunity to every attack.

## Development setup

| Layer | Stack |
|---|---|
| Frontend | Next.js App Router and TypeScript |
| Backend | FastAPI, SQLAlchemy and Alembic |
| Database | PostgreSQL using psycopg3 |
| Authentication | Explicitly configured local accounts, GitHub OAuth, or both; separate API keys |

The following is the existing GitHub-only development setup. Local browser
accounts require the separately documented trusted HTTPS configuration.

```sh
cd backend
python -m venv venv
# Activate the virtual environment for your operating system.
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload
```

```sh
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Configure `VARDRMAP_AUTH_METHODS=github`, `local` or `github,local` consistently
on both services. Do not disable TLS verification or expose the database to fix
setup errors. Apply matching migrations and component versions before using
features that require them.

## Documentation

[API reference](docs/api.md) · [Local authentication](docs/local-authentication.md) ·
[API playbooks](docs/api-playbooks.md) · [Domain model](docs/domain-model.md) ·
[Security model](docs/security-model.md) ·
[Changelog](CHANGELOG.md)

## License

Copyright (C) 2026 Jorge Aquino. VardrMap uses the
[GNU Affero General Public License v3.0](LICENSE). Each independently distributed
component retains its own license. See the license for modification, redistribution
and network-source requirements. Contact the author about separate commercial
terms. VardrRunner is distributed separately under MIT.
