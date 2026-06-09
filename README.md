# VardrMap

A personal bug bounty workflow tool. Manage target programs, track scope, log findings, run recon imports, and draft vulnerability reports — all in one place.

---

## Tech Stack

| Layer | Technology | Hosting |
|---|---|---|
| Frontend | Next.js 16 (App Router, TypeScript) | Vercel |
| Backend | FastAPI (Python 3.14) | Railway |
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

**VardrRunner** — local CLI companion (`runner/`):
- Authenticate with `vardrrunner login vardrmap` using a `vmap_` API key
- Run httpx, nuclei, and subfinder locally; results uploaded automatically
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
| [CHANGELOG.md](CHANGELOG.md) | Version history |

---

## Roadmap

- RBAC / multi-user support
- AI-assisted finding triage and report drafting
- VardrRunner: extract to separate repo (VardrSec/VardrRunner) when API stabilizes
