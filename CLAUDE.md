# VardrMap — Claude Instructions

Professional security testing platform for penetration testing and bug bounty work. FastAPI backend (Railway) + Next.js 16 frontend (Vercel) + PostgreSQL (Railway). GitHub OAuth login; frontend mints short-lived HS256 JWTs for backend requests.

VardrMap is transitioning from a bug bounty dashboard to a full pentest engagement platform. Bug bounty work is now one `engagement_type` (`bug_bounty`) alongside `pentest`, `red_team`, and `internal`. New features should be designed with all engagement types in mind, not just bounty hunting.

## Where things live
- `backend/` — FastAPI app, SQLAlchemy models, Alembic migrations, tests
- `backend/routers/` — one file per resource (engagements, findings, reports, etc.)
- `backend/tests/` — pytest suite (486 tests, uses SQLite)
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


## Vocabulary

The entity is an **Engagement** (`class Engagement`). It was called a *program*
until v0.21; bug bounty work is now one `engagement_type` among several.

Deliberately still named "program":

- the `programs` table and every `program_id` FK column — renaming a live
  Railway table is a separate scheduled change, see `docs/roadmap.md`
- `/programs/*` request paths — rewritten to `/engagements/*` by
  `LegacyProgramPathMiddleware` so VardrRunner and `vmap_` key scripts keep
  working. Delete that class to retire the alias.
- the `programs` key in `GET /engagements` — VardrRunner reads it
- **`RadarProgram`, `radar_programs`, `routers/radar.py`** — these are real bug
  bounty programmes on HackerOne and Bugcrowd. They are not engagements and
  must never be renamed.

## Security
- BOLA/IDOR: every engagement-owned resource scoped by authenticated `github_id` at the DB query level
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

## Engagement types and statuses
`engagement_type`: `bug_bounty` | `pentest` | `red_team` | `internal`
`engagement_status`: `planned` | `active` | `reporting` | `closed`

New engagements default to `bug_bounty` / `active` so existing API callers are unaffected.
Authorization records (`routers/authorizations.py`) track the permission-to-test window — required for pentest/red_team; optional for bug bounty.
Clients (`routers/clients.py`) track the organisation being tested — required for pentest/internal; not applicable for bug bounty.

## Roadmap
Remaining: DB table rename (`programs` → `engagements`, retire legacy path middleware), RBAC / multi-user support, client-facing deliverable generation
