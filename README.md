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
- Stop-work — an emergency brake per engagement that halts every execution until released

**Testing workflow**
- Track in-scope and out-of-scope assets with kind and notes; subdomain coverage requires an explicit wildcard
- Asset graph — canonical identity for hosts, with relationships and provenance, linking recon, services, scans, and findings
- Import tool output — ffuf, httpx, and nuclei (JSON/JSONL)
- Browse recon results and scan findings; update status individually or in bulk
- Log manual test cases with hypothesis, payload, evidence, and status
- Evidence with content hash, sensitivity, and retention — secrets redacted on write
- **Burp-assisted API Surface** — explicitly promote selected Proxy, Repeater, Intruder, Scanner, or Organizer exchanges into a canonical operation inventory with identity/status coverage and retained redacted request/response evidence. Passive capture remains off.
- **API authorization testing** via [VardrGate](https://github.com/VardrSec/VardrGate) — store a test case describing one request replayed as several identities, queue it, and get BOLA / BFLA / cross-tenant / privilege-escalation findings back as triageable results. Credentials are referenced (`value_env` / `value_keychain`), never stored.
- Track findings with severity, asset, status, and full write-up fields
- Draft structured vulnerability reports linked to findings; preview as markdown and export as PDF
- Generate personal API keys (`vmap_` tokens) for external tool access (e.g. Burp Suite)
- Write operations logged to an append-only audit log

**Scan Jobs orchestration console** — full job management UI in the browser:
- Bridge zone — animated link visualization showing live VardrMap ↔ VardrRunner connection status; shows real hostname, OS, version, and per-tool availability from the latest heartbeat
- Telemetry zone — running/completed/results-yielded/avg-runtime stat tiles
- Composer zone — pick one of seven tools (subfinder, httpx, nuclei, nmap, dnsx, naabu, vardrgate) with per-tool config, or a named pipeline: **Attack Surface** (subfinder → dnsx → httpx → nuclei) for a surface you have to discover, **Host Enumeration** (naabu → nmap → httpx) for a scope you were given, **API Assessment** (httpx → vardrgate) for API authorization testing. Selecting a pipeline expands a stage editor so you can include or exclude each stage
- Job Board + Terminal — three board views (Stream, Pipeline, Table); selecting a job opens a terminal that polls live lifecycle events (started → running → done/failed) every 3 s

**VardrRunner** — local CLI companion ([VardrSec/VardrRunner](https://github.com/VardrSec/VardrRunner), its own repo):
- Authenticate with `vardrrunner login vardrmap` using a `vmap_` API key
- `vardrrunner status` — verify config, API connectivity, and local tool availability
- `vardrrunner heartbeat` — report hostname, OS, version, and per-tool availability to VardrMap; auto-sent at start of `jobs run`
- Run httpx, nuclei, and subfinder locally; results uploaded automatically; lifecycle events posted at each stage
- Queue scan jobs from the UI; VardrRunner polls and executes them with `vardrrunner jobs run`
- Wildcard scope entries (`*.example.com`) handled via subfinder enumeration

---

## Scope is advisory

VardrMap evaluates every job against the engagement's authorization, testing window, and scope rules, and **reports what it finds without refusing to run**. Findings come back as a `warnings` array on job creation, claim, and the transition into `running`, carrying stable reason codes (`target_out_of_scope`, `outside_testing_window`, `authorization_missing`, …).

Staying inside scope is the operator's responsibility, the same as it is with every other tool in the kit — Burp proxies any host you point it at, and nmap scans any range you hand it. A platform that blocks on its own reading of a scope rule interrupts legitimate work, and scope in the field is messier than any rule set.

The one exception is **stop-work**, which returns `403` and halts everything. That is not the platform second-guessing the operator: it is the operator's own emergency brake, and a brake that can be ignored is not a brake.

Rationale in [docs/adr/0001-central-policy-engine.md](docs/adr/0001-central-policy-engine.md) § Amendment.

---

## Security Controls

- JWT authentication on all protected routes — HS256, `aud`/`iss`/`exp` validated
- Personal API key authentication — opaque token, SHA-256 hash stored only
- BOLA enforcement — all queries scoped to the authenticated user at the database level; cross-tenant access returns `404`, never `403`
- Secret redaction — auth headers, cookies, tokens, and URL credentials stripped from evidence on write
- Input sanitization — injection detection on identifier fields; `bleach` strip on long-form fields
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
| [docs/implementation-roadmap.md](docs/implementation-roadmap.md) | Phased delivery plan tied to the repository |
| [docs/adr/](docs/adr/) | Architecture decision records |
| [docs/security-testing.md](docs/security-testing.md) | Manual security testing record — BOLA, XSS, SQLi |
| [docs/roadmap.md](docs/roadmap.md) | Forward-looking backlog (next milestone) |
| [CHANGELOG.md](CHANGELOG.md) | Version history |

---

## Roadmap

See [docs/implementation-roadmap.md](docs/implementation-roadmap.md) for the phased plan. Headline items still open:

- **Client-facing deliverable generation** — an engagement-level report, not just per-finding write-ups
- **Finding lifecycle and Retest** — test → report → remediate → retest → verify closed
- **Objectives, TestPlan, TestCase** mapped to WSTG / API Top 10 / ATT&CK
- **Observation** as a first-class entity, distinct from a finding
- Runner API keys scoped to an organization rather than a user
- DB table rename (`programs` → `engagements`) and retirement of the legacy path middleware

Shipped: policy evaluation and stop-work (v0.24), organizations (v0.25), asset graph (v0.26), evidence with redaction (v0.27), advisory scope (v0.29). VardrRunner lives in [its own repo](https://github.com/VardrSec/VardrRunner).
