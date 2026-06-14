# VardrMap

A personal bug bounty workflow tool. Manage target programs, track scope, log findings, run recon imports, and draft vulnerability reports — all in one place.

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

- Create and manage bug bounty target programs
- Track in-scope and out-of-scope assets with kind and notes
- Import tool output — ffuf, httpx, and nuclei (JSON/JSONL)
- Browse recon results and scan findings; update status individually or in bulk
- Log manual test cases with hypothesis, payload, evidence, and status
- Track findings with severity, asset, status, and full write-up fields
- Draft structured vulnerability reports linked to findings; preview as markdown
- Export reports as PDF or markdown
- Generate personal API keys (`vmap_` tokens) for external tool access (e.g. Burp Suite)
- All write operations logged to an append-only audit log

**Scan Jobs orchestration console** — full job management UI in the browser:
- Bridge zone — animated link visualization showing live VardrMap ↔ VardrRunner connection status; shows real hostname, OS, version, and per-tool availability from the latest heartbeat
- Telemetry zone — running/completed/results-yielded/avg-runtime stat tiles
- Composer zone — tool picker (subfinder, httpx, nuclei) with per-tool config; queues a job with one click
- Job Board + Terminal — three board views (Stream, Pipeline, Table); selecting a job opens a terminal that polls live lifecycle events (started → running → done/failed) every 3 s

**VardrRunner** — local CLI companion ([jorge-aquino/VardrRunner](https://github.com/jorge-aquino/VardrRunner), its own repo):
- Authenticate with `vardrrunner login vardrmap` using a `vmap_` API key
- `vardrrunner status` — verify config, API connectivity, and local tool availability
- `vardrrunner heartbeat` — report hostname, OS, version, and per-tool availability to VardrMap; auto-sent at start of `jobs run`
- Run httpx, nuclei, and subfinder locally; results uploaded automatically; lifecycle events posted at each stage
- Queue scan jobs from the UI; VardrRunner polls and executes them with `vardrrunner jobs run`
- Wildcard scope entries (`*.example.com`) handled via subfinder enumeration

---

## Security Controls

- JWT authentication on all protected routes — HS256, `aud`/`iss`/`exp` validated
- Personal API key authentication — opaque token, SHA-256 hash stored only
- BOLA enforcement — all queries scoped to the authenticated user's GitHub ID at the database level
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
| [docs/architecture.md](docs/architecture.md) | Auth flow, data model, component relationships |
| [docs/api.md](docs/api.md) | Full API endpoint reference |
| [docs/development.md](docs/development.md) | Local setup, env vars, migrations, tests |
| [docs/security-testing.md](docs/security-testing.md) | Manual security testing record — BOLA, XSS, SQLi |
| [docs/roadmap.md](docs/roadmap.md) | Forward-looking backlog (next milestone) |
| [CHANGELOG.md](CHANGELOG.md) | Version history |

---

## Roadmap

- Atomic job claim — `POST /jobs/{id}/claim` only updates where `status = 'pending'`, returns 409 if already claimed (race-safe for multiple runner instances)
- Nmap / service discovery — `vardrrunner run nmap --from-recon --top-ports 100`, safe profiles only, stored in a services table
- RBAC / multi-user support
- Opportunities / Target Radar — surface new programs or recently changed scopes
- AI-assisted finding triage and report drafting
- ✅ VardrRunner: extracted to its own repo ([jorge-aquino/VardrRunner](https://github.com/jorge-aquino/VardrRunner))
