# VardrMap

A platform for authorized security testing. Run an engagement for a client under a written authorization: track scope and assets, orchestrate tooling, capture evidence, and produce the findings and reports you hand back.

Bug bounty work is one `engagement_type` among four (`bug_bounty`, `pentest`, `red_team`, `internal`) — a supported mode rather than the centre of gravity.

New Moon source-built capabilities are qualified through the [VardrSec distribution](https://github.com/VardrSec/VardrSec). Its [acceptance ledger](https://github.com/VardrSec/VardrSec/blob/main/docs/new-moon-acceptance.md) distinguishes delivered workflows, remaining safety gates and release approval. A merged component is not a published Community release.

---

## Tech Stack

| Layer | Technology | Hosting |
|---|---|---|
| Frontend | Next.js 16 (App Router, TypeScript) | Compose or Vercel |
| Backend | FastAPI (Python 3.12) | Compose or Railway |
| Database | PostgreSQL (psycopg3) | Compose or Railway |
| Auth | Configured local accounts, GitHub OAuth → Auth.js v5 → backend JWT, or both; separate API keys | — |
| ORM | SQLAlchemy + Alembic | — |

---

## Features

**Engagement model**
- Engagements typed as `bug_bounty`, `pentest`, `red_team`, or `internal`, with status, dates, and a client
- Clients — the organisation the work is performed for; deleting one detaches its engagements rather than deleting the testing record
- Authorization records — who granted permission, the reference (SOW, ticket, policy URL), and the window it covers. `GET /engagements/{id}/authorization/active` answers "is there permission right now?"
- Organizations — tenancy sits on an org, so a teammate can operate an engagement's jobs and share a runner fleet
- Stop-work — prevents new execution. Active cancellation requires the supported controlled Runner path; the legacy policy check alone does not terminate an already running local process

**Testing workflow**
- Track in-scope and out-of-scope assets with kind and notes; subdomain coverage requires an explicit wildcard
- Asset graph — canonical identity for hosts, with relationships and provenance, linking recon, services, scans, and findings
- Import tool output — httpx, nuclei, katana, gau, ffuf and dalfox; supported formats depend on the tool
- Browse recon results and scan findings; update status individually or in bulk
- Log manual test cases with hypothesis, payload, evidence, and status
- Evidence with content hash, sensitivity, and retention — secrets redacted on write
- **Burp-assisted API Surface** — explicitly promote selected Proxy, Repeater, Intruder, Scanner, or Organizer exchanges into a canonical operation inventory with identity/status coverage and retained redacted request/response evidence. Passive capture remains off.
- **API authorization testing** via [VardrGate](https://github.com/VardrSec/VardrGate) — store a test case describing one request replayed as several identities, queue it, and get BOLA / BFLA / cross-tenant / privilege-escalation findings back as triageable results. Credentials are referenced (`value_env` / `value_keychain`), never stored.
- **API assessment outcomes** — distinguish completed commands from conclusive, partial or inconclusive assessments. Claim-time case snapshots and result hashes bind evidence to the reviewed case; conclusive does not mean secure or independently verified.
- **Authorization coverage and review** — operation × identity × boundary gaps, grounded reviewable drafts, and pending AI queue proposals that require operator approval. Unsupported or inconclusive assessments do not count as successful coverage.
- **Execution evidence** — retain job, case and identity provenance, inspect redacted records in the job panel, and link selected evidence to findings. Historical or manual provenance remains unknown.
- **API playbooks** — three original versioned guides shared by the case builder and Runner MCP: ownership/tenant separation, privileged functions, and evidence/retest/handoff. Guidance records no coverage and queues no work.
- Track findings with severity, asset, status, and full write-up fields
- Draft structured vulnerability reports linked to findings; preview as markdown and export as PDF
- Produce engagement-level client deliverables with immutable content revisions, evidence references and hashes; keep them separate from per-finding write-ups
- Generate personal API keys (`vmap_` tokens) for external tool access (e.g. Burp Suite)
- Write operations logged to an append-only audit log

**Scan Jobs orchestration console** — full job management UI in the browser:
- Bridge zone — animated link visualization showing live VardrMap ↔ VardrRunner connection status; shows real hostname, OS, version, and per-tool availability from the latest heartbeat
- Telemetry zone — running/completed/results-yielded/avg-runtime stat tiles
- Composer zone — pick one of ten tools (subfinder, httpx, nuclei, dnsx, naabu, katana, gau, ffuf, dalfox, vardrgate) from a collapsible list with per-tool config, or a named pipeline: **Attack Surface** (subfinder → dnsx → httpx → nuclei) for a surface you have to discover, **Host Enumeration** (naabu → httpx) for a scope you were given, **Content Discovery** (subfinder → httpx → ffuf → katana → gau) for endpoint discovery, **API Assessment** (httpx → vardrgate) for API authorization testing. Selecting a pipeline expands a stage editor so you can include or exclude each stage
- Job Board + Terminal — three board views (Stream, Pipeline, Table); selecting a job opens a terminal that polls live lifecycle events (started → running → done/failed) every 3 s

**VardrRunner** — local CLI companion ([VardrSec/VardrRunner](https://github.com/VardrSec/VardrRunner), its own repo):
- Install the isolated CLI from PyPI with `pipx install vardrrunner`; update it with `vardrrunner update` (0.50.0+; older copies run `pipx upgrade vardrrunner` once). New managed workflows require the reviewed source-built cohort, not merely a package installation
- Set up a machine with `vardrrunner init --url <api-url>`: it prompts for a runner-scoped `vmap_` key (stored in the OS keychain), names the runner and runs `doctor`. Ordinary setup installs no startup service and starts no worker
- `vardrrunner tools install --all` — install, update or repair the pinned scan tools; safe to rerun
- `vardrrunner doctor` — check config, API connectivity and local tool availability; heartbeats report hostname, OS, version and per-tool status to VardrMap
- Run the ten supported recon/scanner tools locally, or execute queued VardrGate authorization cases; results uploaded automatically and lifecycle events posted at each stage
- Queue scan jobs from the UI, then execute them on the runner machine with `vardrrunner jobs run`
- The source-built Full distribution also provides [explicit managed setup](https://github.com/VardrSec/VardrSec/blob/main/docs/local-managed-setup.md). Worker enablement and individual job approval remain separate; normal startup stays inert
- Wildcard scope entries (`*.example.com`) handled via subfinder enumeration

---

<a id="scope-is-advisory"></a>

## Scope and execution modes

**Legacy/manual workflows retain advisory policy behavior.** Scope, testing-window
and authorization concerns are reported as `warnings` on job creation, claim and
transition into `running`, with stable codes such as `target_out_of_scope`,
`outside_testing_window` and `authorization_missing`. These warnings alone are
not an execution boundary; the operator remains responsible for authorized scope.

**Controlled managed workflows are different.** The reviewed Map/Runner path uses
signed authorization, issuer/origin/job binding, credential grants, expiry and
execution budgets. Strict-mode refusals are enforced through that path. An
ordinary queued job or API key is not a substitute for its required approval.
Existing manual behavior is not silently migrated to managed mode.

Stop-work blocks new execution. Supported controlled workers also observe stop and
permission state to cancel active work within their documented bounds. This does
not establish instantaneous remote cancellation during a disconnect or remove
unaccepted host/suspension behavior. See the [worker operator guide](https://github.com/VardrSec/VardrSec/blob/main/docs/nm2-worker-operator.md)
and [current safety dispositions](https://github.com/VardrSec/VardrSec/blob/main/docs/new-moon-architecture-review.md).

The [original advisory-policy rationale](docs/adr/0001-central-policy-engine.md)
remains a historical compatibility decision, not a description of every newer
execution mode.

---

## Security Controls

- Protected routes accept configured local browser sessions, browser JWTs or personal API keys through the same ownership and organization checks
- Browser JWT validation — HS256; `sub`, `aud`, `iss` and `exp` required, with signature, audience, issuer and expiry validated
- Local sessions — Argon2id passwords, secure HTTP-only cookies, server-side expiration/revocation, and Origin plus CSRF checks on cookie-authenticated writes
- Personal API key authentication — opaque token, SHA-256 hash stored only
- BOLA enforcement — database access combines ownership, organization membership and engagement invitations; inaccessible resources return `404`, and viewers cannot write
- Secret redaction — auth headers, cookies, tokens, and URL credentials stripped from evidence on write
- Input sanitization — injection detection on identifier fields; `nh3` strip on long-form fields
- Rate limiting — 200 requests/minute per IP (slowapi)
- Security headers — API: CSP, HSTS (production only), X-Frame-Options, Referrer-Policy, Permissions-Policy. Web pages: X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy and a CSP limited to `frame-ancestors`, `base-uri` and `object-src`; a script-source policy is not yet set
- File upload validation — extension allowlist (`.json`, `.jsonl`), content-type check, 2 MB limit
- Webhook SSRF guard — outbound notification URLs require HTTPS; the host is resolved and re-checked at send time and blocked from private/loopback/link-local/metadata addresses (rebinding-resistant), with redirects disabled

---

## Quick Start

For a source-built local platform, follow the VardrSec distribution
[installation guide](https://github.com/VardrSec/VardrSec/blob/main/docs/installation.md).
It provides Compose lifecycle, trusted local HTTPS, an explicit terminal account
bootstrap and Runner diagnostics. Starting the platform does not start scans.

Login methods are selected explicitly with `VARDRMAP_AUTH_METHODS=github`, `local`
or `github,local` on both services. Local accounts use the existing user, ownership
and organization permissions. Read [local authentication](docs/local-authentication.md)
for password/session controls, bootstrap and recovery. GitHub OAuth remains available
for hosted deployments; its credentials are required only when that provider is enabled.

The snippets below are the default **GitHub-only development** setup. Local-account
browser development requires trusted HTTPS for both UI and API; these HTTP dev
servers alone do not provide it. See [docs/development.md](docs/development.md) for
environment variables, migrations and tests.

**Backend (short version):**
```bash
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1   # Windows
# source venv/bin/activate    # macOS/Linux
pip install -r requirements.txt
cp .env.example .env          # fill in values
uvicorn main:app --reload
```

**Frontend (short version):**
```bash
cd frontend
npm install
cp .env.example .env.local    # fill in values
npm run dev
```

---

## Documentation

| Document | Contents |
|---|---|
| [docs/product-vision.md](docs/product-vision.md) | What this is, the operating model, and what it deliberately is not |
| [docs/architecture.md](docs/architecture.md) | Auth flow, data model, component relationships |
| [docs/domain-model.md](docs/domain-model.md) | Entity map, what exists today, and how each gap closes |
| [docs/security-model.md](docs/security-model.md) | Threat model, scope-matching rules, tenant isolation |
| [docs/api.md](docs/api.md) | Full API endpoint reference |
| [docs/development.md](docs/development.md) | Development setup, env vars, migrations, tests |
| [docs/local-authentication.md](docs/local-authentication.md) | Configured login methods, HTTPS, terminal account bootstrap and recovery |
| [docs/api-playbooks.md](docs/api-playbooks.md) | Original versioned API engagement guidance and human review boundaries |
| [scripts/integration/README.md](scripts/integration/README.md) | Disposable Map → Runner → Gate acceptance and hosted staging boundaries |
| [docs/implementation-roadmap.md](docs/implementation-roadmap.md) | Historical phased delivery plan; not current acceptance status |
| [docs/adr/](docs/adr/) | Dated architecture decisions and rationale, not a live completion scoreboard |
| [docs/security-testing.md](docs/security-testing.md) | Manual security testing record — BOLA, XSS, SQLi |
| [docs/roadmap.md](docs/roadmap.md) | Backlog and proposals; reconcile dated entries against merged source and the distribution ledger |
| [CHANGELOG.md](CHANGELOG.md) | Version history |

---

## Roadmap

The [New Moon acceptance ledger](https://github.com/VardrSec/VardrSec/blob/main/docs/new-moon-acceptance.md)
records the accepted source-built Community scope. Managed authorization and
budgets, supported controlled cancellation, per-identity boundary coverage and
operator-reviewed queue proposals now have implementation and qualification
records; they should not be treated as wholly unimplemented backlog items.

[docs/roadmap.md](docs/roadmap.md) retains follow-on proposals. Broader stateful
coverage, unqualified network/platform modes and remaining research/release gates
are not implied complete by the delivered features. Deploy matching backend
migrations and reviewed component versions; neither branch content nor component
CI alone establishes production deployment or release approval.

---

## License

Copyright (C) 2026 Jorge Aquino.

VardrMap is free software licensed under the **GNU Affero General Public License v3.0**. You may use, study, modify, and redistribute it under those terms — see [`LICENSE`](LICENSE) for the full text. Because VardrMap is typically run as a network service, the AGPL's §13 applies: **if you run a modified version and let others interact with it over a network, you must offer them the complete corresponding source of your modified version.**

As the sole copyright holder, Jorge Aquino can also make VardrMap available under separate commercial terms. If the AGPL does not fit your use, contact the author about a commercial license.

VardrRunner is distributed separately under the MIT license to keep the client easy to adopt.
