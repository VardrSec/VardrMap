# VardrMap — Claude Instructions

## What this project is
Personal bug bounty workflow tool. FastAPI backend (Railway) + Next.js 16 frontend (Vercel) + PostgreSQL (Railway). Users log in with GitHub OAuth; the frontend mints a short-lived HS256 JWT for backend requests.

## Where things live
- `backend/` — FastAPI app, SQLAlchemy models, Alembic migrations, tests
- `backend/routers/` — one file per resource (programs, findings, reports, etc.)
- `backend/tests/` — pytest suite, 63 tests, uses SQLite
- `frontend/app/` — Next.js App Router pages and components
- `frontend/app/components/` — one component per section (FindingsSection, ReportsSection, JobsSection, etc.)
- `frontend/app/context/` — AppContext.tsx + appReducer.ts (global state)
- `runner/` — VardrRunner v1 local CLI; separate venv, installable via `pip install -e ./runner`
- `runner/vardrrunner/` — Python package: config, api client, subprocess runner, command modules
- `runner/tests/` — 40 tests; all subprocess and HTTP calls are mocked
- `docs/` — architecture, API reference, development setup, security testing record
- `CHANGELOG.md` — version history, updated with every change

## Hard rules — never break these
- Never add "Co-Authored-By: Claude" to commits
- Run `npm run lint` and `npm run build` in `frontend/` before committing frontend changes
- Every behavior-changing code change needs matching documentation (see Documentation rules below)

## Security expectations
- Preserve BOLA/IDOR protections: every program-owned resource must be scoped by the authenticated `github_id` at the database query level
- Never return whether another user's object exists — keep cross-user access as `404`, not `403`
- Do not store raw API keys or secrets — store only hashes
- New auth behavior must include tests for: unauthorized, wrong-user, revoked/invalid token, and success cases

## Documentation rules
Every behavior-changing change must update the right files. A change is behavior-changing if it adds, removes, or modifies an endpoint, field, model, env var, auth rule, or user-visible feature. Refactors that don't change any of those do not require a CHANGELOG entry.

- New or changed endpoint → `docs/api.md`
- New model, field, or relationship → `docs/architecture.md` data model section
- New env var or setup step → `docs/development.md`
- Any feature, fix, or behavior change → `CHANGELOG.md` under the current version

Documentation-only, test-only, and pure refactor commits may note "No user-facing docs change needed" in the commit summary.

## Verification before commit

Backend changes:
```
cd backend
.\venv\Scripts\pytest.exe tests -v
```

Frontend changes:
```
cd frontend
npm run lint
npm run build
```

Runner changes:
```
cd runner
.\venv\Scripts\pytest.exe tests -v
```

## Running locally

Backend:
```
cd backend
uvicorn main:app --reload
```

Note: `create_all` only runs in development/test. In production, Railway runs `bash start.sh` which calls `alembic upgrade head` before uvicorn. Never remove this guard.

Frontend:
```
cd frontend
npm run dev
```

## Current roadmap

Shipped (v0.10.0):
- Workflow navigation model: 7-section sidebar (Dashboard, Scope, Run, Review, Findings, Reports, Settings)
- Dashboard: 6 quick-action buttons + inline program edit form (Program Profile section removed)
- Run section: orchestration console (Jobs tab) + file import (Import tab); absorbs Scan Jobs + Imports sections
- Review section: RECON | SCANS | MANUAL tab switcher wrapping existing sub-components
- Deep-link navigation: `navigateToRun(tool)` pre-selects tool in Composer via runPrefill state

Shipped (v0.9.0):
- Frontend app state extracted into context/reducer (AppContext + appReducer)
- PDF report export (jsPDF, client-side)
- Scan job queue — UI creates jobs, VardrRunner polls and executes locally
- VardrRunner: subfinder support for wildcard scope entries
- VardrRunner: `vardrrunner jobs list` and `vardrrunner jobs run`
- VardrRunner: missing tool marks job failed instead of silently skipping
- CI: runner tests added to GitHub Actions workflow
- Scan Jobs orchestration console — Bridge, Telemetry, Composer, JobBoard (stream/pipeline/table), Terminal with live log streaming

Remaining:
- Run / Jobs: wire real API (replace mock seed data with `GET /programs/{id}/jobs`; SSE stream for live logs)
- RBAC / multi-user support
- VardrRunner: extract to separate repo (VardrSec/VardrRunner) when API stabilizes
- AI-assisted finding triage and report drafting
