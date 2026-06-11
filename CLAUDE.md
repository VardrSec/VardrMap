# VardrMap — Claude Instructions

## What this project is
Personal bug bounty workflow tool. FastAPI backend (Railway) + Next.js 16 frontend (Vercel) + PostgreSQL (Railway). Users log in with GitHub OAuth; the frontend mints a short-lived HS256 JWT for backend requests.

## Where things live
- `backend/` — FastAPI app, SQLAlchemy models, Alembic migrations, tests
- `backend/routers/` — one file per resource (programs, findings, reports, etc.)
- `backend/tests/` — pytest suite, 86 tests, uses SQLite
- `frontend/app/` — Next.js App Router pages and components
- `frontend/app/components/` — one component per section (FindingsSection, ReportsSection, JobsSection, etc.)
- `frontend/app/context/` — AppContext.tsx + appReducer.ts (global state)
- `runner/` — VardrRunner v1 local CLI; separate venv, installable via `pip install -e ./runner`
- `runner/vardrrunner/` — Python package: config, api client, subprocess runner, command modules
- `runner/tests/` — 58 tests; all subprocess and HTTP calls are mocked
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

Shipped (v0.13.0):
- Job events — `job_events` table + migration 0006; `POST /jobs/{id}/events` (VardrRunner posts lifecycle events); `GET /jobs/{id}/events` (Terminal polls)
- VardrRunner posts started/targets_resolved/running/uploaded/done/failed events via `_emit()` helper
- Terminal polls events at 3 s while job is pending/running; maps event kinds to colored log lines; stops on terminal state

Shipped (v0.12.0):
- VardrRunner real heartbeat — `POST /runner/heartbeat` + `GET /runner/status`; Bridge shows real hostname, version, OS, and per-tool availability with version chips
- `vardrrunner heartbeat` explicit command; auto-heartbeat at start of `vardrrunner jobs run`
- `runner_heartbeats` table + migration 0005; online = `last_seen < 5 min ago`

Shipped (v0.11.0):
- Scan Jobs console wired to live API — real `GET /programs/{id}/jobs` polling; `POST` to queue, `PATCH` to cancel; adaptive 5s/30s polling
- VardrRunner subfinder job dispatch fixed — proper wildcard extraction → subfinder → JSONL → httpx import
- Simulation engine removed (initJobs, computeYield, RUNNER, THROUGHPUT stubs gone)

Shipped (v0.10.0):
- Workflow navigation model: 7-section sidebar (Dashboard, Scope, Overview, Review, Findings, Reports, Settings)
- Dashboard: orchestration console (Jobs tab) + file import (Import tab); absorbs Scan Jobs + Imports sections
- Overview: 6 quick-action buttons + inline program edit form (Program Profile section removed)
- Review section: RECON | SCANS | MANUAL tab switcher wrapping existing sub-components
- Deep-link navigation: `navigateToDashboard(tool)` pre-selects tool in Composer via runPrefill state

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
- Atomic job claim — `POST /jobs/{id}/claim` only updates where `status = 'pending'`, returns 409 if already claimed
- Nmap / service discovery — `vardrrunner run nmap --from-recon --top-ports 100`, safe profiles only, store as services table
- RBAC / multi-user support
- Opportunities / Target Radar — new programs or changed scopes
- AI-assisted finding triage and report drafting
- VardrRunner: extract to separate repo (VardrSec/VardrRunner) when API stabilizes
