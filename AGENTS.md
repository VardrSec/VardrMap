# VardrMap — Codex Instructions

Penetration testing platform. FastAPI backend (Railway) + Next.js 16 frontend (Vercel) + PostgreSQL (Railway). GitHub OAuth login; frontend mints short-lived HS256 JWTs for backend requests.

VardrMap started as a bug bounty dashboard and is now a professional pentest engagement platform. Bug bounty is one `engagement_type` among four — it is a supported mode, not the centre of gravity. The unit of work is an **engagement** performed for a **client** under a written **authorization**, and the deliverable is a report handed to that client.

**Design every feature for the pentest case first**, then check it degrades sensibly for bounty work. A feature that only makes sense for bounty hunting probably does not belong here — the Submissions tracker was removed in v0.23.0 for exactly that reason.

**Do not introduce bounty framing into new UI copy, prompts, or models.** No payouts, no "accepted/paid" outcomes, no platform-submission language. The one legitimate exception is Target Radar (below), which describes genuinely external bounty programmes.

## Where things live
- `backend/` — FastAPI app, SQLAlchemy models, Alembic migrations, tests
- `backend/routers/` — one file per resource (engagements, findings, reports, etc.)
- `backend/tests/` — pytest suite (700+ tests, uses SQLite)
- `frontend/app/` — Next.js App Router pages and components
- `frontend/app/components/` — one component per section (FindingsSection, ReportsSection, JobsSection, etc.)
- `frontend/app/context/` — AppContext.tsx + appReducer.ts (global state)
- `frontend/test-utils/` — `renderWithApp` harness (75+ frontend tests)
- `docs/` — architecture, API reference, development setup, security testing record
- `CHANGELOG.md` — version history
- VardrRunner lives in its own repo; integrates over HTTP API with a `vmap_` key — no code here.

## Hard rules
- **`git fetch` before starting.** `main` is protected and everything lands via PR, so local `main` is routinely behind. Check `git status -sb` and `gh run list --limit 1` before writing code, not before pushing.
- **New migration:** `alembic heads` must return exactly one line afterwards. Two branches whose revisions name the same `down_revision` is a failed `alembic upgrade head`, which means `start.sh` fails and Railway does not come up. Check `CHANGELOG.md` for the version you intend to claim, too.
- **Destructive migrations need explicit sign-off.** Dropping a table or column deletes production data on the next Railway deploy. Say so plainly and get a yes before writing it; note the data loss in the migration docstring.
- No "Co-Authored-By: Codex" in commits
- Run `npm run lint` + `npm run typecheck` + `npm run build` in `frontend/` before committing frontend changes
- Every behavior-changing change needs matching documentation

## Vocabulary

The entity is an **Engagement** (`class Engagement`). It was called a *program*
until v0.21.

Deliberately still named "program":

- the `programs` table and every `program_id` FK column — renaming a live
  Railway table is a separate scheduled change, see `docs/roadmap.md`
- `/programs/*` request paths — rewritten to `/engagements/*` by
  `LegacyProgramPathMiddleware` so VardrRunner and `vmap_` key scripts keep
  working. Delete that class to retire the alias.
- the `programs` key in `GET /engagements` — VardrRunner reads it
- **`RadarProgram`, `radar_programs`, `routers/radar.py`** — these are real bug
  bounty programmes on HackerOne and Bugcrowd. They are not engagements and
  must never be renamed. Radar is the one place bounty vocabulary (including
  `max_payout`) is correct, because it describes someone else's programme.

## Security
- **Scope is advisory, not enforced.** `policy.py` evaluates every job against authorization, testing window and scope; findings ride back as a `warnings` array and the job still runs. Staying in scope is the operator's responsibility — Burp and nmap don't police their users either. Do not add blocking behaviour to this path. The one exception is stop-work (`403`), the operator's own halt switch. See ADR 0001 § Amendment.
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
Frontend: `cd frontend && npm run lint && npm run typecheck && npm test && npm run build`

`npm run typecheck` (`tsc --noEmit`) is the only thing that type-checks test files —
`next build` only reaches what the app graph imports, and ts-jest transpiles
without checking. It runs in CI inside the required **Frontend lint + build** job.

Note: `renderWithApp` casts through `as unknown as AppContextValue`, which
defeats excess-property checking. Removing something from `AppContext` will not
fail typecheck there — grep `frontend/test-utils/` by hand.

## Running locally
Backend: `cd backend && uvicorn main:app --reload`
Note: `create_all` runs only in dev/test. Production: Railway runs `bash start.sh` → `python wait_for_db.py` → `alembic upgrade head` → uvicorn. Never remove this guard.

The readiness wait is load-bearing: Railway boots the container and Postgres together, and a database in recovery returns `FATAL: the database system is starting up`. Without it, alembic fails, `set -e` kills the container, and `restartPolicyMaxRetries: 3` is spent before the database is ready.

Frontend: `cd frontend && npm run dev`

Auth.js v5 reads `AUTH_SECRET` / `AUTH_GITHUB_ID` / `AUTH_GITHUB_SECRET`. The v4
name `NEXTAUTH_URL` is not read by anything; `AUTH_URL` is optional and inferred
from the request.

## Sections
`Section` in `frontend/app/types.ts` has exactly 7 values:
`dashboard` | `scope` | `overview` | `review` | `findings` | `reports` | `settings`

`DashboardSection` and `ReviewSection` are thin tab containers rendering child
sections with `hideHeader`.

## Engagement types and statuses
`engagement_type`: `bug_bounty` | `pentest` | `red_team` | `internal`
`engagement_status`: `planned` | `active` | `reporting` | `closed`

New engagements default to `bug_bounty` / `active` so existing API callers are unaffected.
Authorization records (`routers/authorizations.py`) track the permission-to-test window — required for pentest/red_team; optional for bug bounty.
Clients (`routers/clients.py`) track the organisation being tested — required for pentest/internal; not applicable for bug bounty.

## Roadmap
Remaining: DB table rename (`programs` → `engagements`, retire legacy path middleware), RBAC / multi-user support, client-facing deliverable generation
