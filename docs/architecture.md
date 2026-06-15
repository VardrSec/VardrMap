# Architecture

## Product Family

VardrMap is part of the VardrSec product family. Each product is a separate deployable unit that integrates with the others via the VardrMap API and `vmap_` API keys.

| Product | Purpose | Status |
|---|---|---|
| VardrMap | Web app — stores programs, scope, findings, reports, recon, scans | Active |
| VardrRunner | Local CLI runner — runs tools on the user's machine, uploads results | Separate repo: [jorge-aquino/VardrRunner](https://github.com/jorge-aquino/VardrRunner) |
| VardrVault | Secrets management for VardrSec products | Planned |
| VardrScanner | Purpose-built scanning engine | Planned |

VardrRunner was extracted from this monorepo into its own repository,
[jorge-aquino/VardrRunner](https://github.com/jorge-aquino/VardrRunner). It integrates with
VardrMap purely over the HTTP API using a `vmap_` key — there is no runner code in this
repo. The section below documents the **integration contract** (how the runner consumes
VardrMap's API); install, CLI, and runner internals are documented in the VardrRunner repo.

---

## VardrMap Overview

VardrMap is a two-service application. The frontend is a Next.js app deployed on Vercel. The backend is a FastAPI app deployed on Railway, backed by a Railway-hosted PostgreSQL database. The browser (running the Vercel-served Next.js app) calls the backend **directly** at `NEXT_PUBLIC_API_URL` over HTTPS, sending the short-lived HS256 JWT — minted by the frontend after GitHub OAuth — in the `Authorization` header. (Routing these calls through a server-side proxy to keep the token out of browser-side JavaScript is a candidate future hardening; today the calls are direct.)

```
Browser (runs the Next.js app served by Vercel)
  │
  │  API calls: HTTPS directly to NEXT_PUBLIC_API_URL
  │  Authorization: Bearer <HS256 JWT>
  ▼
Railway (FastAPI)
  │
  │  psycopg3 (SSL required)
  ▼
Railway (PostgreSQL)
```

---

## Deployment and Schema Management

The backend is deployed on Railway. On every deploy, Railway runs `bash start.sh`, which:

1. Runs `alembic upgrade head` — applies any pending migrations against the production PostgreSQL database
2. Starts `uvicorn main:app` on the Railway-provided `$PORT`

`Base.metadata.create_all()` is guarded to only run when `ENV=development` or `ENV=test`. It never runs in production. Alembic is the sole schema authority for production and staging.

Local development still uses `create_all` for convenience — no migration step needed to start the server. Tests rebuild the SQLite schema from scratch on every run.

---

## Authentication Flow

There are two accepted token types. Both arrive on the `Authorization: Bearer <token>` header.

### Browser JWT (normal login)

1. User clicks "Sign in with GitHub"
2. Auth.js v5 completes the GitHub OAuth flow and mints a session
3. On every request, the frontend's `authFetch` helper calls `getServerSideSession()` to get the current session and reads `backendToken` from it
4. `backendToken` is a short-lived HS256 JWT signed by the frontend using `BACKEND_JWT_SECRET`, with claims: `sub` (GitHub ID), `username`, `email`, `iss` (`vardrmap-frontend`), `aud` (`vardrmap-backend`), `exp` (1 hour)
5. The backend's `get_current_user` dependency verifies the JWT against `BACKEND_JWT_SECRET` and extracts the claims

### Personal API Key (external tools)

1. User generates a key in the Settings section — the backend creates `vmap_` + `secrets.token_urlsafe(32)`, stores only the SHA-256 hash in `api_keys`, and returns the plaintext token once
2. The external tool sends `Authorization: Bearer vmap_<token>` on every request
3. `get_current_user` detects the `vmap_` prefix, hashes the token, looks up the hash in `api_keys`, and resolves the user from `github_id`
4. The token never appears in the database again after generation — only the hash does

Both paths return the same `{"github_id": ..., "username": ..., "email": ...}` dict, so all downstream route handlers are unaware of which auth method was used.

---

## Data Model

All primary keys are UUID strings. All tables have `created_at` (UTC datetime).

```
users
  github_id (PK)
  username
  email
  webhook_url (VARCHAR 500 — Discord/Slack incoming webhook; "" = notifications off)
  notify_min_severity ("info"|"low"|"medium"|"high"|"critical" — finding notification threshold)
  created_at

programs
  id (PK)
  owner_github_id (FK → users.github_id)
  name, platform, program_url
  scope_summary, severity_guidance, safe_harbor_notes
  created_at
  → scope_items, findings, reports, manual_tests,
    recon_items, scan_items, import_records, scan_jobs, services, submissions (all cascade delete)

scope_items
  id (PK), program_id (FK), scope_type ("in"|"out")
  value, kind, notes, created_at

findings
  id (PK), program_id (FK)
  title, severity, asset, status
  summary, steps, impact, remediation
  created_at

reports
  id (PK), program_id (FK)
  finding_id (soft ref — no FK constraint)
  title, summary, steps, impact, remediation
  cwe, cvss, status
  created_at

manual_tests
  id (PK), program_id (FK)
  title, hypothesis, payload, evidence, status
  created_at

recon_items
  id (PK), program_id (FK), source ("ffuf"|"httpx")
  url, path, host, title, status_code, webserver,
  port, tech, content_type, length, words, lines, notes
  first_seen_at (nullable datetime — set once at first import, never overwritten; used for dedup)
  job_id (nullable VARCHAR — soft ref to the scan_job that produced this item)
  created_at

scan_items
  id (PK), program_id (FK), source ("nuclei")
  template_id, title, severity, asset, matched_at,
  type, description, status, cwe, cvss
  created_at

import_records
  id (PK), program_id (FK)
  tool_type, filename (always "redacted"), imported_count
  created_at

api_keys
  id (PK)
  github_id (FK → users.github_id, indexed)
  key_hash (SHA-256 hex, unique)
  label, created_at
  scope (VARCHAR 20 — "full" (default) or "runner"; runner keys may only call jobs/imports/heartbeat)
  last_used_at (nullable — stamped on every successful API key auth)

scan_jobs
  id (PK)
  program_id (FK → programs.id, CASCADE DELETE, indexed)
  owner_github_id (indexed)
  tool_type ("httpx"|"nuclei"|"subfinder"|"nmap")
  target_source ("scope"|"recon")
  config (JSON — tool-specific options: status_code/limit for httpx; severity/templates for nuclei; top_ports/timing for nmap)
  status ("pending"|"running"|"done"|"failed")
  created_at, started_at (nullable), completed_at (nullable)
  error_message

services
  id (PK)
  program_id (FK → programs.id, CASCADE DELETE, indexed)
  owner_github_id (indexed)
  host (VARCHAR 500)
  port (INTEGER 1–65535)
  protocol ("tcp"|"udp")
  service_name, product, version
  state ("open"|"filtered")
  source (default "nmap")
  created_at
  last_scanned_at (nullable datetime — stamped on every upsert, reflects when port was last seen by nmap)

radar_programs
  id (PK)
  owner_github_id (indexed — one set of rows per user)
  platform (VARCHAR 20 — "bugcrowd" | "hackerone")
  platform_id (VARCHAR 200 — unique slug/handle on the platform)
  name (VARCHAR 300)
  url (VARCHAR 500)
  max_payout (nullable INTEGER)
  is_new (VARCHAR 1 — "1" = unseen since last refresh, "0" = seen; marked "0" when GET /radar delivers it)
  discovered_at (UTC datetime — when first inserted)
  last_fetched_at (UTC datetime — updated on every POST /radar/refresh)
  Indexes: owner_github_id; (platform, platform_id)

submissions
  id (PK)
  program_id (FK → programs.id, CASCADE DELETE, indexed)
  owner_github_id (indexed)
  finding_id, report_id (soft refs — no FK constraints)
  platform (VARCHAR 50 — "HackerOne", "Bugcrowd", etc.)
  platform_reference (VARCHAR 200 — report ID or URL)
  title (VARCHAR 200)
  status ("submitted"|"triaged"|"accepted"|"duplicate"|"na"|"paid"|"rejected")
  payout_usd (nullable FLOAT)
  severity (VARCHAR 20 — copied from finding for display)
  submitted_at (nullable datetime), resolved_at (nullable datetime)
  notes (TEXT)
  created_at

runner_heartbeats
  id (PK)
  owner_github_id (indexed)
  hostname, version, os_info
  tools (JSON — {"httpx": {"ok": true, "version": "v1.6.9"}, ...})
  last_seen (UTC datetime — frontend derives online = last_seen < 5 min ago)
  Unique: (owner_github_id, hostname) — one row per user per machine

scheduled_scans
  id (PK)
  program_id (FK → programs.id, CASCADE DELETE, indexed)
  owner_github_id (indexed)
  tool_type ("httpx"|"nuclei"|"subfinder"|"nmap")
  target_source ("scope"|"recon")
  config (JSON — same shape and validation as scan_jobs.config)
  interval ("hourly"|"daily"|"weekly")
  enabled (BOOLEAN — paused schedules are skipped at materialization)
  last_run_at (nullable datetime — when a job was last materialized)
  next_run_at (datetime — schedule is due when <= now)
  created_at

job_events
  id (PK)
  job_id (FK → scan_jobs.id, CASCADE DELETE, indexed)
  owner_github_id (indexed)
  kind ("started"|"targets_resolved"|"running"|"uploaded"|"done"|"failed"|"log")
  text (detail message — target count, result count, error text, etc.)
  created_at (UTC datetime)

program_members
  id (PK)
  program_id (FK → programs.id, CASCADE DELETE, indexed)
  owner_github_id (indexed — the program owner, for fast BOLA checks)
  member_github_id (indexed — the invited collaborator)
  role (VARCHAR 20 — "member"; future: "admin")
  invited_at
  Unique: (program_id, member_github_id)

audit_logs
  id (PK)
  github_id (no FK — records survive user deletion)
  action ("create"|"update"|"delete")
  resource_type, resource_id, program_id
  timestamp
```

**Notes:**
- `Report.finding_id` is a soft reference — no FK constraint. Reports can exist without a linked finding.
- `AuditLog` has no FK constraints so records are never deleted when users or programs are removed.
- `api_keys.key_hash` stores the SHA-256 hex digest of the plaintext token. The plaintext is never stored. `last_used_at` is stamped on every successful API key authentication. `scope` restricts runner-scoped keys to jobs/imports/heartbeat endpoints — all other endpoints return `403` for runner keys.
- `recon_items.first_seen_at` is set once when an item is first imported and never overwritten. Dedup key is `(program_id, source, url)`: re-importing the same URL produces `new_count: 0` with no duplicate row.
- `program_members` grant collaborators read+write access to a program's resources. Only the owner can manage members and delete/PATCH the program itself. `GET /programs` returns both owned programs and programs where the user is a member.
- `scan_jobs.config` is a JSON column with optional tool options. VardrRunner reads this dict when executing the job. Unknown config keys are rejected at creation time.
- `scan_jobs` are scoped to the owning user via `owner_github_id` — a user can only see/update their own jobs. Claiming a job uses `POST /jobs/{id}/claim` which atomically sets `status = "running"` only if currently `"pending"`, returning 409 otherwise.
- `services` rows are bulk-upserted on `(host, port, protocol)` — repeated nmap scans update metadata rather than creating duplicates. `last_scanned_at` is stamped on both insert and update so freshness is always visible.
- `radar_programs` are upserted per user on `(owner_github_id, platform, platform_id)`. New programs land with `is_new = "1"` so the Overview Radar widget can badge them; `GET /radar` marks all returned rows as seen.
- `submissions` track the full lifecycle of a bug bounty submission. `finding_id` and `report_id` are soft references — submissions survive finding/report deletion. Transitioning `status` to a terminal state (`accepted`, `duplicate`, `na`, `paid`, `rejected`) via `PATCH` auto-stamps `resolved_at` if it was not already set.
- Deleting a `scan_job` (via `DELETE /jobs/{id}`) also deletes all its `job_events` via CASCADE.
- `runner_heartbeats` is upserted per `(owner_github_id, hostname)` so multiple machines (laptop + VPS) report independently. VardrRunner calls `POST /runner/heartbeat` at the start of `jobs run`, every 60 s inside the daemon, and via `vardrrunner heartbeat`. The frontend polls `GET /runner/status` which returns all runners and derives per-runner `online: true` if `last_seen` is within 5 minutes. Rate-limited to 60/min.
- `scheduled_scans` have no backend cron. Due schedules (`enabled` and `next_run_at <= now`) are materialized into pending `scan_jobs` inside `GET /jobs/pending` — the runner's poll drives the clock. `next_run_at` advances from *now* rather than the previous `next_run_at`, so a runner that was offline for a week creates one catch-up job, not seven.
- `users.webhook_url` (stored plaintext — it must be usable, unlike hashed API keys; only ever returned to its owner) and `users.notify_min_severity` drive outbound notifications, sent via FastAPI BackgroundTasks so webhook latency never delays API responses. URLs are validated against an SSRF guard (HTTPS only, no localhost/private/link-local targets).
- `job_events` are appended by VardrRunner via `POST /jobs/{id}/events` at each lifecycle stage. The frontend Terminal polls `GET /jobs/{id}/events` (3 s interval while job is pending/running, stops on terminal state). Events cascade-delete with their parent job. Rate-limited to 600/min.

---

## Program Serialization (Lazy Loading)

`GET /programs` and `GET /programs/{id}` return aggregate stats rather than full arrays. This avoids loading potentially large result sets on every program fetch.

```python
# serialize_program returns:
{
  "id": ...,
  "name": ...,
  # ... program fields ...
  "scope": { "in": [...], "out": [...] },   # always loaded — typically small
  "imports": [...],                          # always loaded — typically small
  "recon_count": <int>,                      # COUNT query
  "scans_count": <int>,                      # COUNT query
  "manual_tests_count": <int>,               # COUNT query
  "findings_count": <int>,                   # COUNT query
  "findings_by_severity": { "critical": 0, "high": 1, ... },  # GROUP BY
  "findings_by_status":   { "new": 1, "triaged": 0, ... },    # GROUP BY
  "reports_count": <int>,                    # COUNT query
}
```

Each section component fetches its own full data set with a separate request when it mounts or after a mutation. After a mutation, sections call `refreshSelectedProgram()` from `AppContext` to re-fetch the program object and keep the dashboard counts current. Global state (session, programs, active section, prefill data) lives in `AppContext` / `appReducer` — sections call `useAppContext()` rather than receiving props.

### Navigation Model

The sidebar exposes **7 top-level sections** mapped to the bug bounty workflow:

| Section | `Section` value | What it shows |
|---|---|---|
| Dashboard | `"dashboard"` | Orchestration console (Jobs tab) + file import (Import tab) |
| Scope | `"scope"` | In-scope / out-of-scope asset management |
| Overview | `"overview"` | Program stats, 6 quick-action buttons, inline program edit form |
| Review | `"review"` | Recon / Scans / Manual / Services tab switcher |
| Findings | `"findings"` | Finding log with severity, status, promote-to-report flow |
| Reports | `"reports"` | Report drafting and PDF export |
| Settings | `"settings"` | API key management |

`DashboardSection` and `ReviewSection` are thin tab containers. They render child section components (`JobsSection`, `ReconSection`, etc.) with `hideHeader={true}` to suppress duplicate section headings. The `Section` type union in `frontend/app/types.ts` has exactly these 7 values.

**Deep-link navigation** — the Overview quick-action buttons dispatch `NAVIGATE_TO_DASHBOARD` which sets `state.dashboardPrefill = { tool?, tab? }` and navigates to `"dashboard"`. `DashboardSection` consumes the prefill via `useEffect`, increments `prefillEpoch` (so `Composer` remounts even when the same tool is clicked twice), sets the active tab and forwards `defaultTool` to `JobsSection` → `Composer`, then dispatches `DASHBOARD_PREFILL_CONSUMED`.

### Dashboard Section — Orchestration Console

`JobsSection` (`frontend/app/components/JobsSection.tsx`) is hosted inside `DashboardSection`'s Jobs tab and rendered as four stacked zones:

1. **Bridge** (`jobs/Bridge.tsx`) — animated link visualization showing VardrMap ↔ VardrRunner connection; runner node shows real hostname, OS, version, and per-tool availability chips from the latest heartbeat; collapses to a slim strip. Collapse state persists to `localStorage`.
2. **Telemetry** (`jobs/Telemetry.tsx`) — four stat tiles: running, completed, results yielded, avg runtime.
3. **Composer** (`jobs/Composer.tsx`) — tool picker (subfinder/httpx/nuclei/nmap) with per-tool config fields; submits new jobs.
4. **Job Board + Terminal** (`jobs/JobBoard.tsx`, `jobs/Terminal.tsx`) — three switchable board views (Stream, Pipeline, Table); a terminal showing status and any backend error message for the selected job.

The `ScanJobUI` type (`frontend/app/types.ts`) extends the API-level `ScanJob` with UI-only fields (`progress`, `yield`, `yieldKind`, `durationMs`, `log[]`). Jobs are loaded via real API polling (5 s when active jobs exist, 30 s idle). The Terminal polls `GET /jobs/{id}/events` every 3 s while the job is pending or running, displaying lifecycle events (`started`, `targets_resolved`, `running`, `uploaded`, `done`/`failed`) as colored log lines; polling stops when the job reaches a terminal state.

---

## File Upload Pipeline

`POST /programs/{program_id}/imports` accepts a multipart form with `tool_type` and `file`.

Validation order:
1. File extension must be `.json` or `.jsonl`
2. Content-Type must be `application/json`, `application/x-ndjson`, `application/octet-stream`, or `text/plain`
3. File size must not exceed `MAX_UPLOAD_BYTES` (default 2 MB)
4. Content is parsed as JSON array or JSONL (one object per line)
5. Items are passed to the tool-specific parser (`parse_ffuf`, `parse_httpx`, `parse_nuclei`)
6. An `ImportRecord` is written with `filename = "redacted"` — original filenames often leak local paths and have no value post-import

---

## VardrRunner Architecture

VardrRunner is a local CLI that runs offensive tools on the user's machine and uploads results to VardrMap. Scan traffic always comes from the user's IP — tools never run on Railway.

```
User's machine
  │
  │  vardrrunner run nuclei --program <id> --from-recon
  ▼
VardrRunner (separate repo)
  │  1. fetch recon targets from VardrMap API
  │     GET /programs/{id}/recon?limit=100&status_code=200
  │
  │  2. show dry-run preview, ask for confirmation
  │
  │  3. run tool locally via subprocess (arg list, no shell=True)
  │     nuclei -l targets.txt -json-export output.jsonl
  │
  │  4. save raw output to ~/.vardrmap/runs/<timestamp>/
  │
  │  5. upload via existing import endpoint
  │     POST /programs/{id}/imports  (multipart, tool_type=nuclei)
  ▼
VardrMap backend (Railway)
  │  parse, store, deduplicate → ScanItem rows
  ▼
VardrMap frontend (Vercel)
  │  display in Scanning section review queue
```

**Key design constraints** (enforced in the VardrRunner repo):
- Scan traffic always originates from the user's machine — tools never run on Railway.
- Tool execution uses an allowlist and safe profiles only (e.g. nmap never uses `-A`, `-O`, `-p-`, `--script`, or `-T5`); subprocesses are always invoked with an argument list, never `shell=True`.
- Recon targets are normalized to host form before nmap; the `vmap_` API key is stored locally (`~/.vardrmap/config.json`, restricted permissions on Unix).
- Raw tool output is saved locally before upload, so a failed upload never loses data.

For the full tool allowlist, target-resolution flags, and CLI reference, see the
[VardrRunner docs](https://github.com/jorge-aquino/VardrRunner/tree/main/docs).

### Job Queue Flow

The UI can queue jobs that VardrRunner picks up and executes. This decouples scan scheduling (done in the browser) from scan execution (done on the user's machine).

```
Browser (VardrMap UI)
  │  POST /programs/{id}/jobs  { tool_type, target_source, config }
  ▼
Railway (FastAPI) — stores ScanJob row, status = "pending"

User's machine
  │  vardrrunner jobs run
  ▼
VardrRunner (separate repo)
  │  1. GET /jobs/pending  — fetch pending jobs for this user
  │  2. POST  /jobs/{id}/claim      — atomically claim; 409 if already claimed
  │  3. POST  /jobs/{id}/events     — kind = "started"
  │  4. resolve targets (same logic as manual run commands)
  │  5. POST  /jobs/{id}/events     — kind = "targets_resolved"
  │  6. execute tool locally via subprocess
  │  7. POST  /jobs/{id}/events     — kind = "running"
  │  8. upload results via POST /programs/{id}/imports
  │  9. POST  /jobs/{id}/events     — kind = "uploaded"
  │ 10. PATCH /jobs/{id}            — status = "done" | "failed"
  │ 11. POST  /jobs/{id}/events     — kind = "done" | "failed"
  ▼
VardrMap backend — results stored; job status visible in Jobs section
```

If the required tool is not on PATH, the job is immediately marked `failed` with an error message — it does not stay stuck as `pending`.
