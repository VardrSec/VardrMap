# VardrMap — Claude Instructions

Personal bug bounty workflow tool. FastAPI backend (Railway) + Next.js 16 frontend (Vercel) + PostgreSQL (Railway). GitHub OAuth login; frontend mints short-lived HS256 JWTs for backend requests.

## Where things live
- `backend/` — FastAPI app, SQLAlchemy models, Alembic migrations, tests
- `backend/routers/` — one file per resource (programs, findings, reports, etc.)
- `backend/tests/` — pytest suite (302 tests, uses SQLite)
- `frontend/app/` — Next.js App Router pages and components
- `frontend/app/components/` — one component per section (FindingsSection, ReportsSection, JobsSection, etc.)
- `frontend/app/context/` — AppContext.tsx + appReducer.ts (global state)
- `docs/` — architecture, API reference, development setup, security testing record
- `CHANGELOG.md` — version history
- VardrRunner lives in its own repo; integrates over HTTP API with a `vmap_` key — no code here.

## Hard rules
- No "Co-Authored-By: Claude" in commits
- Run `npm run lint` + `npm run build` in `frontend/` before committing frontend changes
- Every behavior-changing change needs matching documentation

## Security
- BOLA/IDOR: every program-owned resource scoped by authenticated `github_id` at the DB query level
- Cross-user access → `404`, not `403` (never reveal existence of another user's object)
- Store only hashes of API keys/secrets, never raw values
- New auth behavior needs tests: unauthorized, wrong-user, revoked/invalid token, success

## Documentation rules
Behavior-changing = adds, removes, or modifies an endpoint, field, model, env var, auth rule, or user-visible feature.

- New/changed endpoint → `docs/api.md`
- New model, field, or relationship → `docs/architecture.md` (data model section)
- New env var or setup step → `docs/development.md`
- Any feature/fix/behavior change → `CHANGELOG.md`

Docs-only, test-only, pure-refactor commits may note "No user-facing docs change needed."

## Verification
Backend: `cd backend && .\venv\Scripts\pytest.exe tests -v`
Frontend: `cd frontend && npm run lint && npm run build`

## Running locally
Backend: `cd backend && uvicorn main:app --reload`
Note: `create_all` runs only in dev/test. Production: Railway runs `bash start.sh` → `alembic upgrade head` → uvicorn. Never remove this guard.

Frontend: `cd frontend && npm run dev`

## Roadmap
Remaining: RBAC / multi-user support
