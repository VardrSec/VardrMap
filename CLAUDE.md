# VardrMap — Claude Instructions

Authorized security research and engagement-management platform: FastAPI backend + Next.js 16 frontend + PostgreSQL. It is the researcher interface and control plane of the VardrSec platform (see the parent `CLAUDE.md` and `VardrSec/docs/community-alpha.md`). Map owns engagements, authorization/scope, identities, jobs, findings, evidence and reports. Runner executes tools; Gate performs authorization assessment; the VardrSec distribution repo owns packaging and recovery. Do not duplicate those responsibilities here.

## Deployment directions
Both are supported. Do not assume hosted services are mandatory for a local installation.
- **Local-first (current release focus):** Docker Compose via the VardrSec distribution, local PostgreSQL, local authentication, trusted HTTPS, user-controlled engagement data. Container notes: `docs/containers.md`; readiness/status: `docs/platform-status.md`, ADR 0003.
- **Hosted compatibility:** Vercel frontend, Railway backend + PostgreSQL, GitHub OAuth with short-lived HS256 JWTs minted by the frontend. Existing organization and tenant controls apply unchanged. Never break this path to simplify local mode.

## Authentication
`VARDRMAP_AUTH_METHODS` = `github` (default) | `local` | `github,local`, set on backend and frontend; invalid values fail closed. Local authentication (ADR 0004, `docs/local-authentication.md`) is implemented on `main` but listed as unreleased in `CHANGELOG.md`. Preserve:
- Argon2id password hashing (64 MiB, t=3, p=4); login rate limit and account lockout; generic failure responses.
- Database-backed revocable sessions (only SHA-256 digests stored), `__Host-` secure HTTP-only cookie, absolute and idle expiry. Local mode requires HTTPS; there is no localhost exception.
- CSRF: session-bound token plus allowed-Origin check on every cookie-based write.
- Bootstrap and recovery are terminal-only (`python -m local_accounts ...`); no default password, public bootstrap route or registration endpoint.
- Local mode never bypasses ownership, organization, tenant or BOLA checks. A local account is not a superuser.
- Migration `0031localauth` refuses automatic downgrade; keep a verified backup before upgrading real data.

## Product identity
An **engagement** is authorized security work: a professional penetration test, an internal assessment, a red-team exercise, or a bug bounty / independent research effort. `engagement_type` has four values (`bug_bounty`, `pentest`, `red_team`, `internal`); self-directed research uses an existing type, and not every engagement has a paying client. Keep the code-enforced rules as they are: clients are required for `pentest`/`internal`, authorization records for `pentest`/`red_team`. Reporting stays to professional standards.

Do not introduce payout, "accepted/paid" or platform-submission framing in new UI copy, prompts or models. The one exception is Target Radar (below), which describes genuinely external bounty programmes. A feature that only suits one workflow should degrade sensibly for the others; the Submissions tracker was removed in v0.23.0 for being bounty-only.

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
- No "Co-Authored-By: Claude" in commits
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

Queueable `tool_type`: `httpx` | `nuclei` | `subfinder` | `nmap` | `dnsx` | `naabu` |
`katana` | `gau` | `ffuf` | `dalfox` | `vardrgate_api_test`. Config keys are allowlisted per
tool in `routers/jobs.py`, with bounds mirroring VardrRunner's so a bad value is refused at
queue time rather than failing on the operator's machine after a runner claims the job.
**`ffuf.wordlist` is a name, never a path** — a path would let the API name any file the
runner can read for ffuf to read and replay at a target.

**There are no recurring scans.** VardrRunner runs only when invoked, so a schedule could
never fire on its own; `/schedules` and the `scheduled_scans` table were removed (migration
`0029dropschedules`). Every job runs once, when the operator runs `vardrrunner jobs run`. Do
not reintroduce scheduling or anything that implies jobs run unattended.

**Request controls.** The Composer's Request Controls set `rate` (httpx/nuclei/katana/ffuf)
and `headers` (those plus dalfox) on a job and on every pipeline stage that accepts them.
`frontend/app/lib/requestControls.ts` mirrors the backend's `_validate_headers` and rate
bounds; change both together.

**Scanner output is a candidate, not a finding.** nuclei and dalfox imports land as
`scan_items` with `status: "new"`; promoting one is the operator's act. Keep the scanner's
own signal separate from our severity — dalfox's tier goes in `type`, with
`detection_method` and `confidence` in their own columns — and never map a tier to a
confirmed status, however confident the tool is. dalfox imports are deduplicated on the
query-less URL + `template_id` + tier; never key that on the payload or PoC URL, which
carry a fresh per-run marker class.
**Scanner payload, evidence and PoC URL are stored exactly as reported** (`payload`,
`match_evidence`, `asset`): never run them through `strip_html`, which deletes anything
tag-shaped — for an XSS scanner that deletes the evidence. Sanitise prose,
not data. They are untrusted text: render only as text. **The same goes for recon URLs**
(`url`/`host`/`path` via `_url_field`): the previous sanitizer turned `?a=1&b=2` into `?a=1&amp;b=2`,
and recon URLs are read back as scan targets. Existing rows were not rewritten — read
`docs/recon-url-recovery-plan.md` before touching them; a blind decode is wrong.

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
updates to conserve tokens.

## Roadmap
See `docs/roadmap.md` for the current backlog: physical table rename and legacy alias
retirement, organization administration, organization-bound runner credentials,
reviewed login/refresh, broader API guidance, engagement-wide execution budgets,
signed contracts, running-process cancellation, retention policy and remote MCP OAuth.
RBAC, finding activity/retests and reviewed case authoring are implemented.

Client-facing deliverable generation shipped in v0.39.0 (immutable client report revisions).

Agent-facing tools and instruction-only prompts live in VardrRunner's MCP server.
Case/report drafting and methodology checklists are implemented; the shared playbook
and evidence reads use Map endpoints. Remote MCP remains a joint design requiring
backend OAuth. See `docs/roadmap.md` for current gaps rather than treating these
implemented features as future work.

Remote MCP has a [proposed authorization design](docs/adr/0002-remote-mcp-authorization.md),
not an accepted implementation plan. Merging that ADR does not settle its provider,
grant binding, remote writes, consent or token-lifecycle decisions. Do not start
OAuth implementation until those decisions are explicitly accepted.
