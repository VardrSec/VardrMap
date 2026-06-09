# VardrMap — Claude Instructions

## What this project is
Personal bug bounty workflow tool. FastAPI backend (Railway) + Next.js 16 frontend (Vercel) + PostgreSQL (Railway). Users log in with GitHub OAuth; the frontend mints a short-lived HS256 JWT for backend requests.

## Where things live
- `backend/` — FastAPI app, SQLAlchemy models, Alembic migrations, tests
- `backend/routers/` — one file per resource (programs, findings, reports, etc.)
- `backend/tests/` — pytest suite, 42 tests, uses SQLite
- `frontend/app/` — Next.js App Router pages and components
- `frontend/app/components/` — one component per section (FindingsSection, ReportsSection, etc.)
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

## Running locally

Backend:
```
cd backend
uvicorn main:app --reload
```

Frontend:
```
cd frontend
npm run dev
```

## Current roadmap
- Paginate findings and reports
- Extract frontend app state into context/reducer
- Authenticated scanning from the UI
- PDF report export
- RBAC / multi-user support
