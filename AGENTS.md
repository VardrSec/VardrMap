# VardrMap — agent instructions

Shared rules for every coding agent (Claude Code imports this file from `CLAUDE.md`;
Codex reads it directly). They must hold even when this repository is cloned on its own.

VardrMap is the researcher interface and control plane of the VardrSec platform:
FastAPI backend, Next.js 16 frontend, PostgreSQL. It owns engagements,
authorization/scope, identities, jobs, findings, evidence and reports. VardrRunner
executes tools (over the HTTP API with a `vmap_` key; no Runner code here), VardrGate
performs authorization assessment, and the VardrSec distribution repo owns packaging
and recovery. Do not duplicate those responsibilities here.

Where to look: [`docs/architecture.md`](docs/architecture.md) (layout, data model,
auth flows, navigation, Runner/Gate records), [`docs/development.md`](docs/development.md)
(setup, env vars, tests, migrations), [`docs/api.md`](docs/api.md),
[`docs/domain-model.md`](docs/domain-model.md),
[`docs/security-model.md`](docs/security-model.md),
[`docs/local-authentication.md`](docs/local-authentication.md),
[`docs/roadmap.md`](docs/roadmap.md), [`docs/adr/`](docs/adr/). Current release
priorities: `docs/community-alpha.md` in the VardrSec repository.

## Safety floor
- No scan or tool execution without explicit authorization; tests use local fixtures.
- Never log, print, commit or report credentials, tokens, `.env` contents or
  engagement data.
- No force-push, history rewrite, release, image publication or deployment without
  explicit authorization. `main` is protected; everything lands via PR.
- `git fetch && git status -sb` and `gh run list --limit 1` before writing code —
  local `main` is routinely behind.
- No AI attribution: no `Co-Authored-By` trailers or "Generated with" lines. Commits
  carry a DCO sign-off (`git commit -s`; see `CONTRIBUTING.md`).

## Deployment directions
Both are supported; never break one to simplify the other.
- **Local-first** (current release focus): Docker Compose via the VardrSec
  distribution, local PostgreSQL, local authentication, trusted HTTPS
  (`docs/containers.md`, `docs/platform-status.md`, ADR 0003).
- **Hosted compatibility:** Vercel frontend, Railway backend + PostgreSQL, GitHub
  OAuth with short-lived HS256 JWTs minted by the frontend. Organization and tenant
  controls apply unchanged.
- Production starts with `bash start.sh` → `python wait_for_db.py` →
  `alembic upgrade head` → uvicorn. `create_all` runs only in dev/test. Never remove
  the readiness wait: without it alembic fails while Postgres recovers, `set -e`
  kills the container and Railway's restart budget is spent.

## Authentication and sessions
`VARDRMAP_AUTH_METHODS` = `github` (default) | `local` | `github,local`, on backend and
frontend; invalid values fail closed. Local authentication (ADR 0004) must keep:
- Argon2id (64 MiB, t=3, p=4); login rate limit and account lockout; generic failures.
- Database-backed revocable sessions storing only SHA-256 digests; `__Host-` secure
  HTTP-only cookie; absolute and idle expiry. Local mode requires HTTPS — no
  localhost exception.
- CSRF: session-bound token plus allowed-Origin check on every cookie-based write.
- Bootstrap and recovery are terminal-only (`python -m local_accounts ...`): no default
  password, public bootstrap route or registration endpoint.
- Local mode never bypasses ownership, organization, tenant or BOLA checks; a local
  account is not a superuser.
- Browser JWTs require `exp`, `sub`, `aud`, `iss`; keep signature, expiry, audience
  and issuer verification. Runner-only keys cannot read full engagement evidence or
  playbooks. Store only hashes of API keys and secrets.

## Authorization and tenancy
- **BOLA/IDOR:** use the shared access predicates in `deps.py` (direct ownership,
  organization membership, engagement invitations). An owner-only filter wrongly
  excludes authorized teammates.
- Cross-user access returns **404**, never 403 — don't reveal another user's object.
- Viewers read shared resources but cannot write: apply `require_member_write` and the
  client-specific organization role checks on mutations.
- New auth behavior needs tests: unauthorized, wrong user, revoked/invalid token, success.
- **Scope is advisory, not enforced.** `policy.py` evaluates every job against
  authorization, testing window and scope; findings return as `warnings` and the job
  still runs. Do not add blocking behavior. The one exception is stop-work (`403`),
  the operator's own halt switch (ADR 0001 § Amendment).

## Jobs and scanner data
- **No recurring scans.** Runner runs only when invoked; `/schedules` and
  `scheduled_scans` were removed (`0029dropschedules`). Do not reintroduce scheduling
  or anything implying unattended execution.
- Queueable `tool_type`s and their config keys are allowlisted in `routers/jobs.py`,
  with bounds mirroring VardrRunner's. **`ffuf.wordlist` is a name, never a path** — a
  path would let the API make the runner read and replay any local file.
- Request controls: `frontend/app/lib/requestControls.ts` mirrors the backend's
  `_validate_headers` and rate bounds; change both together.
- **Scanner output is a candidate, not a finding.** nuclei/dalfox imports land as
  `scan_items` with `status: "new"`; promotion is the operator's act. Keep the
  scanner's signal (dalfox tier in `type`, `detection_method`, `confidence`) separate
  from our severity and never map a tier to a confirmed status. Deduplicate dalfox on
  query-less URL + `template_id` + tier, never on payload or PoC URL.
- **Scanner payload, evidence and PoC URL are stored exactly as reported**: never run
  them through `strip_html` (it deletes XSS evidence). Sanitize prose, not data;
  render untrusted text only as text. Recon URLs (`_url_field`) likewise; read
  `docs/recon-url-recovery-plan.md` before touching existing rows — a blind decode is wrong.

## Runner/Gate contracts and evidence
- Job completion and assessment completeness are separate: `done` means execution
  finished; `conclusive` means declared identities have definite outcomes and a
  working legitimate baseline — not that the API is secure.
- Gate claims freeze an unresolved `ScanJob.case_snapshot`; Runner hashes it as
  `case_hash` (never resolved secrets). A conflicting upload hash fails; a missing
  binding stays inconclusive. Never evaluate against a later edit.
- Gate evidence keeps job/case/identity and expected/observed decisions. Job/case
  deletion uses SET NULL and retains evidence; preserve receipt replay compatibility
  and immutable report/activity snapshots. Historical/manual assessment metadata
  stays unknown (`0027assessments`); never infer or rewrite it.
- `backend/api_playbooks.json` is the versioned catalog shared with Runner MCP; its
  schema rejects undeclared fields; guidance stores no progress or coverage and
  queues no work. Viewers may read; only writers may link evidence.
- Human review stays explicit: saving cases declares review; retest recording and
  client deliverable revisions (immutable) are operator actions. Identity preflight
  failures remain inconclusive.
- Legacy names are contracts: the `programs` table and `program_id` columns,
  `/programs/*` paths (rewritten by `LegacyProgramPathMiddleware` for Runner and
  `vmap_` scripts) and the `programs` key in `GET /engagements` stay until a
  scheduled change (`docs/roadmap.md`). `RadarProgram`/`radar_programs` are real
  external bounty programmes and must never be renamed.
- Deploy the matching backend migration/endpoints before publishing a companion
  Runner feature. Unreleased branch content is not proof of a production deployment.
- Remote MCP has only a *proposed* design (ADR 0002); do not start OAuth
  implementation until its decisions are explicitly accepted.

## Product identity
An engagement is authorized security work: pentest, internal assessment, red team, or
bug bounty / independent research (`engagement_type`: `bug_bounty` | `pentest` |
`red_team` | `internal`). New engagements default to `bug_bounty`/`active` so existing
API callers are unaffected. Keep the code-enforced rules: clients required for
`pentest`/`internal`, authorization records for `pentest`/`red_team`. No payout,
"accepted/paid" or platform-submission framing in new UI copy, prompts or models
(Target Radar excepted). A feature suited to one workflow must degrade sensibly for
the others.

## Migrations
- `alembic heads` must return exactly one line after a new revision; check
  `CHANGELOG.md` for the version you claim.
- **Destructive migrations need explicit sign-off**: dropping a table or column
  deletes production data on the next deploy. Say so plainly, get a yes, and note the
  data loss in the migration docstring. `0031localauth` refuses automatic downgrade.

## Development rules
- Behavior-changing (endpoint, field, model, env var, auth rule, user-visible feature)
  → update `docs/api.md`, `docs/architecture.md` (data model) or
  `docs/development.md` (env/setup) as relevant, and always `CHANGELOG.md`.
- Backend: `cd backend && .\venv\Scripts\pytest.exe tests -v`.
  Frontend: `cd frontend && npm run lint && npm run typecheck && npm test && npm run build`
  before committing frontend changes. PostgreSQL migration checks and browser
  acceptance run in CI; local fixtures do not verify hosted OAuth or production.
- Docs-only changes: review the diff, check Markdown links and `git diff --check`.
- `frontend/AGENTS.md` holds the Next.js rules that `next dev` maintains (Claude Code
  loads it through `frontend/CLAUDE.md`); follow it for frontend work.
