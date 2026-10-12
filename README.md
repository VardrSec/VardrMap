# VardrMap

A platform for authorized security testing. Run an engagement for a client under a written authorization: track scope and assets, orchestrate tooling, capture evidence, and produce the findings and reports you hand back.

Bug bounty work is one `engagement_type` among four (`bug_bounty`, `pentest`, `red_team`, `internal`) — a supported mode rather than the centre of gravity.

---

## Tech Stack

| Layer | Technology | Hosting |
|---|---|---|
| Frontend | Next.js 16 (App Router, TypeScript) | Vercel |
| Backend | FastAPI (Python 3.12) | Railway |
| Database | PostgreSQL (psycopg3) | Railway |
| Auth | GitHub OAuth → Auth.js v5 → backend JWT (HS256) | — |
| ORM | SQLAlchemy + Alembic | — |

---

## Features

**Engagement model**
- Engagements typed as `bug_bounty`, `pentest`, `red_team`, or `internal`, with status, dates, and a client
- Clients — the organisation the work is performed for; deleting one detaches its engagements rather than deleting the testing record
- Authorization records — who granted permission, the reference (SOW, ticket, policy URL), and the window it covers. `GET /engagements/{id}/authorization/active` answers "is there permission right now?"
- Organizations — tenancy sits on an org, so a teammate can operate an engagement's jobs and share a runner fleet
- Stop-work — prevents new execution and pauses schedule materialization until released; already running processes are not cancelled

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
- Composer zone — pick one of eleven tools (subfinder, httpx, nuclei, nmap, dnsx, naabu, katana, gau, ffuf, dalfox, vardrgate) with per-tool config, or a named pipeline: **Attack Surface** (subfinder → dnsx → httpx → nuclei) for a surface you have to discover, **Host Enumeration** (naabu → nmap → httpx) for a scope you were given, **Content Discovery** (subfinder → httpx → katana → gau) for endpoint discovery, **API Assessment** (httpx → vardrgate) for API authorization testing. Selecting a pipeline expands a stage editor so you can include or exclude each stage
- Job Board + Terminal — three board views (Stream, Pipeline, Table); selecting a job opens a terminal that polls live lifecycle events (started → running → done/failed) every 3 s

**VardrRunner** — local CLI companion ([VardrSec/VardrRunner](https://github.com/VardrSec/VardrRunner), its own repo):
- Install the isolated CLI from PyPI with `pipx install vardrrunner` (`uvx vardrrunner …` for one-shot use)
- Authenticate with `vardrrunner login vardrmap` using a `vmap_` API key
- `vardrrunner status` — verify config, API connectivity, and local tool availability
- `vardrrunner heartbeat` — report hostname, OS, version, and per-tool availability to VardrMap; auto-sent at start of `jobs run`
- Run the ten supported recon/scanner tools locally, or execute queued VardrGate authorization cases; results uploaded automatically and lifecycle events posted at each stage
- Queue scan jobs from the UI; VardrRunner polls and executes them with `vardrrunner jobs run`
- Wildcard scope entries (`*.example.com`) handled via subfinder enumeration

---

## Scope is advisory

VardrMap evaluates every job against the engagement's authorization, testing window, and scope rules, and **reports what it finds without refusing to run**. Findings come back as a `warnings` array on job creation, claim, and the transition into `running`, carrying stable reason codes (`target_out_of_scope`, `outside_testing_window`, `authorization_missing`, …).

Staying inside scope is the operator's responsibility, the same as it is with every other tool in the kit — Burp proxies any host you point it at, and nmap scans any range you hand it. A platform that blocks on its own reading of a scope rule interrupts legitimate work, and scope in the field is messier than any rule set.

The one exception is **stop-work**, which returns `403` to prevent new execution and skips schedule materialization; it does not cancel already running local processes. That is not the platform second-guessing the operator: it is the operator's own emergency brake, and a brake that can be ignored is not a brake.

Rationale in [docs/adr/0001-central-policy-engine.md](docs/adr/0001-central-policy-engine.md) § Amendment.

---

## Security Controls

- JWT authentication on all protected routes — HS256; `sub`, `aud`, `iss` and `exp` required, with signature, audience, issuer and expiry validated
- Personal API key authentication — opaque token, SHA-256 hash stored only
- BOLA enforcement — database access combines ownership, organization membership and engagement invitations; inaccessible resources return `404`, and viewers cannot write
- Secret redaction — auth headers, cookies, tokens, and URL credentials stripped from evidence on write
- Input sanitization — injection detection on identifier fields; `nh3` strip on long-form fields
- Rate limiting — 200 requests/minute per IP (slowapi)
- Security headers — CSP, HSTS (production only), X-Frame-Options, Referrer-Policy, Permissions-Policy
- File upload validation — extension allowlist (`.json`, `.jsonl`), content-type check, 2 MB limit
- Webhook SSRF guard — outbound notification URLs require HTTPS; the host is resolved and re-checked at send time and blocked from private/loopback/link-local/metadata addresses (rebinding-resistant), with redirects disabled

---

## Quick Start

See [docs/development.md](docs/development.md) for full setup including environment variables, migrations, and running tests.

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
| [docs/development.md](docs/development.md) | Local setup, env vars, migrations, tests |
| [docs/api-playbooks.md](docs/api-playbooks.md) | Original versioned API engagement guidance and human review boundaries |
| [scripts/integration/README.md](scripts/integration/README.md) | Disposable Map → Runner → Gate acceptance and hosted staging boundaries |
| [docs/platform-comparison-2026-10-11.md](docs/platform-comparison-2026-10-11.md) | Dated ars0n comparison, implementation update and validation limits |
| [docs/implementation-roadmap.md](docs/implementation-roadmap.md) | Historical phased delivery plan; current backlog lives in roadmap.md |
| [docs/adr/](docs/adr/) | Architecture decision records |
| [docs/security-testing.md](docs/security-testing.md) | Manual security testing record — BOLA, XSS, SQLi |
| [docs/roadmap.md](docs/roadmap.md) | Forward-looking backlog (next milestone) |
| [CHANGELOG.md](CHANGELOG.md) | Version history |

---

## Roadmap

See [docs/roadmap.md](docs/roadmap.md) for the current backlog. Remaining work includes identity/session preflight, broader API guidance, organization administration and organization-bound runner credentials, engagement-wide execution budgets, signed contracts, running-process cancellation, remote MCP OAuth, and the physical table rename.

Organization access, finding activity/retest records, reviewed case authoring and client deliverable revisions are implemented. Assessment outcomes, structured execution evidence and shared playbooks are recorded under **Unreleased**; their presence in this branch does not establish a production deployment. Deploy the matching backend migration before releasing the companion Runner changes.

---

## License

Copyright (C) 2026 Jorge Aquino.

VardrMap is free software licensed under the **GNU Affero General Public License v3.0**. You may use, study, modify, and redistribute it under those terms — see [`LICENSE`](LICENSE) for the full text. Because VardrMap is typically run as a network service, the AGPL's §13 applies: **if you run a modified version and let others interact with it over a network, you must offer them the complete corresponding source of your modified version.**

As the sole copyright holder, Jorge Aquino can also make VardrMap available under separate commercial terms. If the AGPL does not fit your use, contact the author about a commercial license.

VardrRunner is distributed separately under the MIT license to keep the client easy to adopt.
