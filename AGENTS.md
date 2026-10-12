# VardrMap — Codex Instructions

Penetration testing platform. FastAPI backend (Railway) + Next.js 16 frontend (Vercel) + PostgreSQL (Railway). GitHub OAuth login; frontend mints short-lived HS256 JWTs for backend requests.

VardrMap started as a bug bounty dashboard and is now a professional pentest engagement platform. Bug bounty is one `engagement_type` among four — it is a supported mode, not the centre of gravity. The unit of work is an **engagement** performed for a **client** under a written **authorization**, and the deliverable is a report handed to that client.

**Design every feature for the pentest case first**, then check it degrades sensibly for bounty work. A feature that only makes sense for bounty hunting probably does not belong here — the Submissions tracker was removed in v0.23.0 for exactly that reason.

**Do not introduce bounty framing into new UI copy, prompts, or models.** No payouts, no "accepted/paid" outcomes, no platform-submission language. The one legitimate exception is Target Radar (below), which describes genuinely external bounty programmes.

## Where things live
- `backend/` — FastAPI app, SQLAlchemy models, Alembic migrations, tests
- `backend/routers/` — one file per resource (engagements, findings, reports, etc.)
- `backend/tests/` — pytest suite (SQLite by default; optional PostgreSQL verification)
- `frontend/app/` — Next.js App Router pages and components
- `frontend/app/components/` — one component per section (FindingsSection, ReportsSection, JobsSection, etc.)
- `frontend/app/context/` — AppContext.tsx + appReducer.ts (global state)
- `frontend/test-utils/` — `renderWithApp` harness (frontend test harness)
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
- BOLA/IDOR: use the shared database access predicates in `deps.py`, combining direct ownership, organization membership and engagement invitations. A direct owner-only filter can wrongly exclude authorized teammates.
- Cross-user access → `404`, not `403` (never reveal existence of another user's object)
- Viewers can read shared resources but cannot write; apply `require_member_write` and the client-specific organization role checks on mutations.
- Browser JWTs require `exp`, `sub`, `aud`, `iss`; preserve signature, expiry, audience and issuer verification. Runner-only keys cannot read full engagement evidence or playbooks.
- Store only hashes of API keys/secrets, never raw values
- New auth behavior needs tests: unauthorized, wrong-user, revoked/invalid token, success

## Documentation rules
Behavior-changing = adds, removes, or modifies an endpoint, field, model, env var, auth rule, or user-visible feature.

- New/changed endpoint → `docs/api.md`
- New model, field, or relationship → `docs/architecture.md` (data model section)
- New env var or setup step → `docs/development.md`
- Any feature/fix/behavior change → `CHANGELOG.md`

Docs-only or test-only changes and pure refactors may note "No user-facing docs change needed." Check changed Markdown links and `git diff --check` for docs-only work; do not rerun application suites solely for prose edits.

## Verification
Backend: `cd backend && .\venv\Scripts\pytest.exe tests -v`
Frontend: `cd frontend && npm run lint && npm run typecheck && npm test && npm run build`

Use focused checks while changing code, then run the relevant full suites before review.
PostgreSQL migration/integration checks and real browser acceptance run in CI.
See `docs/development.md` and `scripts/integration/README.md` for disposable local
validation. Local/browser fixtures do not verify hosted OAuth or production deployment.

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

## API assessments, evidence and guidance

- Job lifecycle and assessment completeness are separate. `done` means execution
  finished; `conclusive` means the declared identities have definite reported
  outcomes and a working legitimate baseline, not that the API is secure.
- Gate claims freeze an unresolved `ScanJob.case_snapshot`. Runner hashes that
  spec as `case_hash`; never hash resolved secrets. A conflicting upload hash
  fails; a missing binding remains inconclusive. Do not evaluate against a later edit.
- Migration `0027assessments` adds nullable assessment/provenance fields after
  `0026dalfox`. Historical/manual metadata stays unknown; do not infer or rewrite it.
- Gate evidence carries job/case/identity and expected/observed decisions. Job/case
  deletion uses SET NULL and retains evidence; preserve receipt replay compatibility
  and immutable report/activity snapshots.
- `backend/api_playbooks.json` is the original versioned catalog shared by the UI
  and Runner MCP. Its schema rejects undeclared fields; guidance stores no progress
  or coverage and queues no work. Viewers may read; only writers may link evidence.
- Saving cases declares human review; retest recording and client deliverable
  revisions stay explicit operator actions. Optional identity preflight checks
  reviewed session metadata before resource testing and stores safe diagnostics;
  missing/failed checks remain inconclusive. Automatic login refresh, signed
  execution contracts and cancellation of running processes remain future work.
- Deploy the matching backend migration/endpoints before publishing the companion
  Runner feature. Unreleased branch content is not proof of a production deployment.

## Communication

Report major results, blockers and required decisions. Omit routine command-by-command
updates to conserve tokens. Revisit the ars0n comparison when the platform changes,
using inspected code and clearly dated evidence; no weekly polling is requested.

## Roadmap
See `docs/roadmap.md` for the current backlog: physical table rename and legacy alias
retirement, organization administration, organization-bound runner credentials,
reviewed identity login/refresh, broader API guidance, engagement-wide execution budgets,
signed contracts, running-process cancellation, retention policy and remote MCP OAuth.
RBAC, client deliverables, finding activity/retests, reviewed case authoring and the
current unreleased assessment/provenance/playbook work are implemented.
