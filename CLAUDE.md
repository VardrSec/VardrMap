# VardrMap — Claude Instructions

## Engineering Charter — shared across all VardrSec repos
<!-- This section is identical in VardrMap, VardrRunner, and VardrVault.
     Edit it in one repo, then mirror the change to the other two. -->

Every VardrSec repo is built to a product-grade bar: **revolutionary in intent, clean in
execution, lean in performance, and fully documented at every step.** Treat nothing here
as "just a script."

### 1. Organization — a place for everything
- One concern per module, one responsibility per function. No god files.
- Fixed homes: source, tests, docs, changelog, and ADRs each live in a predictable place.
- No stray files at the repo root. Experiments go in `scratch/` (gitignored) or are deleted.
- Dead code, commented-out blocks, and unused dependencies are removed, not parked.
- Every public symbol explains *why* it exists, not just *what* it does.

### 2. Track everything
- `CHANGELOG.md` follows Keep a Changelog + SemVer; updated with every behavior change.
- Every non-trivial design decision gets an ADR in `docs/adr/` (use the template).
- No undocumented releases; every version is dated and described.
- Committed TODOs reference a tracked issue, or they don't get committed.

### 3. Tests are non-negotiable — on every repo
- Every behavior-changing change ships with tests in the **same commit**.
- The suite is always green. Never commit failing or skipped tests without a written reason.
- Cover logic, edge cases, and failure paths — coverage of meaning, not line-count vanity.
- CI runs the full suite on every push; a red build blocks merge.

### 4. Clean code
- Clear names over clever ones. Small functions. Early returns over deep nesting.
- No premature abstraction and no copy-paste — refactor at the third duplication.
- Errors are handled explicitly and surfaced with context, never silently swallowed.
- Match surrounding style; run the formatter and linter before every commit.

### 5. Lean & smooth performance
- Measure before optimizing. Keep hot paths allocation-light and I/O batched.
- Prefer streaming/pagination over loading everything into memory.
- Dependencies are a liability — each new one must earn its place.
- Build, startup, and test times are part of the product; watch for regressions.

### 6. Full software lifecycle, every time
Plan → design (ADR if non-trivial) → implement **with** tests → document → review →
release (changelog + tag) → maintain. No step is skipped, even for small changes.

## What this project is
Personal bug bounty workflow tool. FastAPI backend (Railway) + Next.js 16 frontend (Vercel) + PostgreSQL (Railway). Users log in with GitHub OAuth; the frontend mints a short-lived HS256 JWT for backend requests.

## Where things live
- `backend/` — FastAPI app, SQLAlchemy models, Alembic migrations, tests
- `backend/routers/` — one file per resource (programs, findings, reports, etc.)
- `backend/tests/` — pytest suite, 302 tests, uses SQLite
- `frontend/app/` — Next.js App Router pages and components
- `frontend/app/components/` — one component per section (FindingsSection, ReportsSection, JobsSection, etc.)
- `frontend/app/context/` — AppContext.tsx + appReducer.ts (global state)
- `runner/` — VardrRunner v1 local CLI; separate venv, installable via `pip install -e ./runner`
- `runner/vardrrunner/` — Python package: config, api client, subprocess runner, command modules
- `runner/tests/` — 113 tests; all subprocess and HTTP calls are mocked
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
- Deep-link navigation: `navigateToDashboard(tool)` pre-selects tool in Composer via `dashboardPrefill` state

Shipped (v0.9.0):
- Frontend app state extracted into context/reducer (AppContext + appReducer)
- PDF report export (jsPDF, client-side)
- Scan job queue — UI creates jobs, VardrRunner polls and executes locally
- VardrRunner: subfinder support for wildcard scope entries
- VardrRunner: `vardrrunner jobs list` and `vardrrunner jobs run`
- VardrRunner: missing tool marks job failed instead of silently skipping
- CI: runner tests added to GitHub Actions workflow
- Scan Jobs orchestration console — Bridge, Telemetry, Composer, JobBoard (stream/pipeline/table), Terminal with live log streaming

Shipped (v0.14.0):
- Atomic job claim — `POST /jobs/{id}/claim` returns 409 if not pending; VardrRunner uses this endpoint
- Service discovery — `services` table + migration 0007; nmap job type in VardrRunner (safe profile); `ServicesSection` in frontend Review tab
- Per-tool config validation — unknown keys rejected, nuclei severity and nmap timing validated
- API key `last_used_at` — stamped on every auth, shown in API key list

Shipped (v0.15.0):
- Target Radar — `radar_programs` table + migration 0008; `GET /radar` + `POST /radar/refresh` (Bugcrowd + HackerOne); Overview Radar widget
- AI-assisted triage — `POST /programs/{id}/findings/{id}/suggest` via `claude-haiku-4-5-20251001`; "AI Suggest" button in FindingsSection
- Services → Manual Test promotion — "Investigate" button dispatches `NAVIGATE_TO_REVIEW` with pre-filled manual test
- Per-endpoint rate limits — events 600/min, heartbeat 60/min; shared `limiter.py`
- nmap URL normalization — `strip_url_to_host()` helper; deduplicates after normalization
- `last_scanned_at` on services — stamped on every upsert; shown in ServicesSection

Shipped (v0.16.0):
- Submission tracker — full CRUD (`/programs/{id}/submissions`); `submissions` table + migration 0009; `SubmissionsSection` in frontend; payout tracking, status lifecycle, `resolved_at` auto-stamp
- Report → Submission promotion — "Submit →" button in ReportsSection dispatches `PROMOTE_TO_SUBMISSION` prefill
- Delete stuck job — `DELETE /jobs/{id}`; delete button in Terminal footer
- CI hardening — gitleaks secret scanning, pip-audit, npm audit, alembic heads check

Shipped (v0.17.0):
- VardrRunner daemon — `vardrrunner daemon start/stop/status`; polls jobs every 5 s, heartbeats every 60 s on a dedicated thread, `--detach` background mode with PID file, graceful SIGTERM shutdown
- Extracted `execute_pending_jobs()` from `run_jobs()` so one-shot and daemon share the same execution path

Shipped (v0.17.1):
- Daemon Windows fixes — ctypes liveness probe (os.kill on Windows is TerminateProcess and was killing the daemon), PID-file-removal graceful stop protocol, DETACHED_PROCESS detach, double-start guard
- Backend Postgres `pool_pre_ping=True` — no more stale-connection 500s after Railway idles connections

Shipped (v0.18.0):
- Scheduled scans — `scheduled_scans` table + migration 0010; CRUD at `/programs/{id}/schedules`; due schedules materialize into pending jobs inside `GET /jobs/pending` (runner poll drives the clock, no backend cron); Composer recurrence picker + Recurring Scans panel
- Webhook notifications — `users.webhook_url` + `notify_min_severity`; `GET/PATCH /settings`; fires on job failure and notable nuclei imports via BackgroundTasks; SSRF guard (HTTPS only, no private targets); Settings UI panel
- Multi-runner — heartbeats upserted per `(owner, hostname)`; `GET /runner/status` returns `runners` array; Bridge lists machines
- Radar → Program tracking — "+ Track" button creates a program from a radar entry and jumps to Scope

Remaining:
- RBAC / multi-user support
- VardrRunner: extract to separate repo (VardrSec/VardrRunner) when API stabilizes
