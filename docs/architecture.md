# Architecture

## Product Family

VardrMap is part of the VardrSec product family. Each product is a separate deployable unit that integrates with the others via the VardrMap API and `vmap_` API keys.

| Product | Purpose | Status |
|---|---|---|
| VardrMap | Web app — stores programs, scope, findings, reports, recon, scans | Active |
| VardrRunner | Local CLI runner — runs tools on the user's machine, uploads results | Separate repo: [VardrSec/VardrRunner](https://github.com/VardrSec/VardrRunner) |
| VardrVault | Secrets management for VardrSec products | Planned |
| VardrScanner | Purpose-built scanning engine | Planned |

VardrRunner was extracted from this monorepo into its own repository,
[VardrSec/VardrRunner](https://github.com/VardrSec/VardrRunner). It integrates with
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

1. Runs `python wait_for_db.py` — blocks until Postgres accepts a `SELECT 1`, polling every 2s for up to 120s
2. Runs `alembic upgrade head` — applies any pending migrations against the production PostgreSQL database
3. Starts `uvicorn main:app` on the Railway-provided `$PORT`

Step 1 exists because Railway starts the application container and the Postgres
service concurrently. A database still in recovery answers with `FATAL: the
database system is starting up` rather than refusing the connection, so alembic
exits non-zero and `set -e` kills the container. With
`restartPolicyMaxRetries: 3` in `railway.json`, three fast retries exhaust the
budget in seconds and the deploy fails permanently — waiting out a condition
that clears on its own. Free-tier services cold-start on every deploy, so the
race runs from a stop every time.

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

### API surface and Burp exchanges

`ApiEndpoint` is a canonical HTTP operation scoped to an engagement: method,
host and a path template such as `/users/{id}`. Repeated observations upsert the
same operation. `ApiExchange` is a deliberately promoted request/response pair
linked to that operation, with an operator-provided logical identity label,
response metadata and parameter names.

Raw Proxy history is never synchronized. The Burp extension sends only selected
messages, strips URL query values by retaining only the parsed operation path,
and redacts credentials locally. The backend independently redacts every header
and body again before writing it. Identity labels such as `anonymous`,
`standard-user`, and `admin` describe a test perspective; they do not store or
model the corresponding account or credential.

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
    recon_items, scan_items, import_records, scan_jobs, services (all cascade delete)

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
  job_id (nullable — scan_job that produced this item; null for manual imports)
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
  depends_on (nullable — soft ref to another scan_job; this stage is held out of
    GET /jobs/pending until its parent is "done", auto-failed if the parent failed)
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

scan_profiles
  id (PK)
  program_id (FK → programs.id, CASCADE DELETE, indexed)
  owner_github_id (indexed)
  name (VARCHAR 100)
  tool_type (see routers/jobs.py _VALID_TOOLS)
  target_source ("scope"|"recon")
  config (JSON — same shape and validation as scan_jobs.config)
  created_at

authorization_test_cases
  id (PK)
  program_id (FK → programs.id, CASCADE DELETE, indexed)
  owner_github_id (indexed)
  name (VARCHAR 200)
  test_case_id (VARCHAR 200 — VardrGate's own spec.id, surfaced for traceability;
    not unique, a case may be revised)
  description
  spec (JSON — VardrGate AuthorizationTestCase, stored verbatim)
  created_at, updated_at (nullable)

job_result_receipts
  id (PK)
  job_id (FK → scan_jobs.id, CASCADE DELETE, unique)
  payload_hash (SHA-256 of canonical result JSON)
  scan_items_created, evidence_created
  created_at

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
- `program_members` grant collaborators access to a program's resources, with two roles: **`member`** (read + write) and **`viewer`** (read-only). Only the owner can manage members and delete/PATCH the program itself. `GET /programs` returns both owned programs and programs where the user is a member.
- **Viewer enforcement:** every program-scoped write endpoint (create/update/delete of findings, reports, manual tests, scans, schedules, scan profiles, services, scope, imports, jobs, pipelines) calls `require_member_write` after `get_program_or_404`, which raises `403` for a viewer-role member. The guard fires before any resource lookup, so a viewer gets `403` even for a non-existent target id. Owners always pass; runner-scoped API keys resolve to the owner and therefore also pass (so uploads/heartbeats are unaffected). AI actions (`findings/{id}/suggest`, `scans/triage`) are gated too, since they incur cost. Read (`GET`) endpoints remain open to viewers.
- `scan_jobs.config` is a JSON column with optional tool options. VardrRunner reads this dict when executing the job. Unknown config keys are rejected at creation time.
- `scan_jobs` are scoped to the owning user via `owner_github_id` — a user can only see/update their own jobs. Claiming a job uses `POST /jobs/{id}/claim` which atomically sets `status = "running"` only if currently `"pending"`, returning 409 otherwise.
- `services` rows are bulk-upserted on `(host, port, protocol)` — repeated nmap scans update metadata rather than creating duplicates. `last_scanned_at` is stamped on both insert and update so freshness is always visible.
- `radar_programs` are upserted per user on `(owner_github_id, platform, platform_id)`. New programs land with `is_new = "1"` so the Overview Radar widget can badge them; `GET /radar` marks all returned rows as seen.
- Deleting a `scan_job` (via `DELETE /jobs/{id}`) also deletes all its `job_events` via CASCADE.
- `runner_heartbeats` is upserted per `(owner_github_id, hostname)` so multiple machines (laptop + VPS) report independently. VardrRunner calls `POST /runner/heartbeat` at the start of `jobs run`, every 60 s inside the daemon, and via `vardrrunner heartbeat`. The frontend polls `GET /runner/status` which returns all runners and derives per-runner `online: true` if `last_seen` is within 5 minutes. Rate-limited to 60/min.
- `scheduled_scans` have no backend cron. Due schedules (`enabled` and `next_run_at <= now`) are materialized into pending `scan_jobs` inside `GET /jobs/pending` — the runner's poll drives the clock. `next_run_at` advances from *now* rather than the previous `next_run_at`, so a runner that was offline for a week creates one catch-up job, not seven.
- `users.webhook_url` (stored plaintext — it must be usable, unlike hashed API keys; only ever returned to its owner) and `users.notify_min_severity` drive outbound notifications, sent via FastAPI BackgroundTasks so webhook latency never delays API responses. URLs are validated against an SSRF guard (HTTPS only, no localhost/private/link-local targets).
- `job_events` are appended by VardrRunner via `POST /jobs/{id}/events` at each lifecycle stage. The frontend Terminal polls `GET /jobs/{id}/events` (3 s interval while job is pending/running, stops on terminal state). Events cascade-delete with their parent job. Rate-limited to 600/min.
- **Pipelines** (`POST /programs/{id}/pipelines`) create an ordered chain of `scan_jobs` linked by `depends_on`. A dependent stage is withheld from `GET /jobs/pending` until its parent is `done`; the runner's own poll drives the clock (same pattern as scheduled scans). If a parent `failed`, `GET /jobs/pending` auto-fails the dependent stage so it never hangs. The endpoint accepts any valid ordered chain. The UI offers two named chains from `PIPELINES` (`frontend/app/components/jobs/mockData.tsx`) — Attack Surface (subfinder → dnsx → httpx → nuclei) and Host Enumeration (naabu → nmap → httpx) — with each stage individually includable, so it may post any ordered subset. `depends_on` is linked sequentially over whatever arrives, so a subset still chains correctly.
- **Provenance:** `recon_items.job_id` and `scan_items.job_id` record which `scan_job` produced each row (stamped from the optional `job_id` form field on `POST /imports`; null for manual uploads). `GET /programs/{id}/recon?job_id=` and `GET /programs/{id}/scans?job_id=` filter by it, so the Terminal can deep-link from a finished job to exactly the rows it yielded.
- **AI triage** (`POST /programs/{id}/scans/triage`) sends a batch of un-promoted `scan_items` to Claude (Haiku) and returns a per-item `priority`/`false_positive`/`rationale`. Unlike `findings/{id}/suggest` (which enriches an already-created finding), triage is the first pass over raw tool output. Only ids present in the request are echoed back, so the model cannot smuggle in other rows. Requires `ANTHROPIC_API_KEY`.
- `scan_profiles` are reusable tool + config presets per program, validated identically to `scan_jobs.config`. They let the Composer queue a frequently-used scan in one click. No FK from jobs to profiles — a profile is a template, copied into a job at queue time.
- `authorization_test_cases` store VardrGate specs per engagement. Unlike a scan profile, a test case is **referenced** rather than copied: a job carries `config = {"test_case_id": ...}` and the spec is inlined when the job is handed to a runner. That keeps `scan_jobs.config` flat for validation, lets one case back many runs, and means revising a case does not require re-queueing. `spec` is stored verbatim because VardrGate owns that schema and is free to extend it without a migration here. **Credential values are never stored** — identities reference secrets via `value_env` / `value_keychain`, resolved by VardrRunner on the operator's machine; a literal non-empty `value` is rejected on write.

### VardrGate job lifecycle

`vardrgate_api_test` is the one job type that resolves no scope or recon targets — the request under test travels inside the stored case.

1. **Queue.** `POST /engagements/{id}/jobs` with `config = {"test_case_id": ...}`. The reference is validated at queue time and scoped to the engagement, so a job can neither name a missing case nor borrow one from another engagement.
2. **Hand-off.** `GET /jobs/pending` expands the stored spec into `config.test_case` (`_resolve_test_cases` in `routers/jobs.py`). The spec rides on the response only — it is never written back to `scan_jobs.config`, so the job keeps holding just the id and a revised case changes what the next hand-off carries. **This expansion is what lets the integration land without a VardrRunner release**: `VardrGateConfig.from_dict` receives exactly the object it already expects. A job whose case has been deleted is auto-failed here, the same way a dangling pipeline dependency is.
3. **Result.** `POST /jobs/{id}/upload` verifies the result's test-case id against the queued case, then maps `findings[]` → `scan_items` (`source="vardrgate"`, `template_id` = the stored VardrGate case id) and `executions[]` → `evidence`, including an optional body-free `response_profile`. A unique `job_result_receipts` row makes retries idempotent: the same canonical payload returns the stored counts, while a different second result is rejected. Reusing `scan_items` means the existing triage and promote-to-finding flow applies rather than a parallel one. Everything is redacted on write: VardrGate excludes credential values and response bodies from its own JSON, but a control that depends on the sender behaving is not a control.

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

The sidebar exposes **7 top-level sections** mapped to the engagement workflow:

| Section | `Section` value | What it shows |
|---|---|---|
| Dashboard | `"dashboard"` | Orchestration console (Jobs tab) + file import (Import tab) |
| Scope | `"scope"` | In-scope / out-of-scope asset management |
| Overview | `"overview"` | Engagement stats, 6 quick-action buttons, inline engagement edit form |
| Review | `"review"` | Recon / Scans / Manual / Services tab switcher |
| Findings | `"findings"` | Finding log with severity, status, promote-to-report flow |
| Reports | `"reports"` | Report drafting and PDF export |
| Settings | `"settings"` | API key management and webhook notifications |

`DashboardSection` and `ReviewSection` are thin tab containers. They render child section components (`JobsSection`, `ReconSection`, etc.) with `hideHeader={true}` to suppress duplicate section headings. The `Section` type union in `frontend/app/types.ts` has exactly these 7 values.

**Deep-link navigation** — the Overview quick-action buttons dispatch `NAVIGATE_TO_DASHBOARD` which sets `state.dashboardPrefill = { tool?, tab? }` and navigates to `"dashboard"`. `DashboardSection` consumes the prefill via `useEffect`, increments `prefillEpoch` (so `Composer` remounts even when the same tool is clicked twice), sets the active tab and forwards `defaultTool` to `JobsSection` → `Composer`, then dispatches `DASHBOARD_PREFILL_CONSUMED`.

### Dashboard Section — Orchestration Console

`JobsSection` (`frontend/app/components/JobsSection.tsx`) is hosted inside `DashboardSection`'s Jobs tab and rendered as four stacked zones:

1. **Bridge** (`jobs/Bridge.tsx`) — animated link visualization showing VardrMap ↔ VardrRunner connection; runner node shows real hostname, OS, version, and per-tool availability chips from the latest heartbeat; collapses to a slim strip. Collapse state persists to `localStorage`.
2. **Telemetry** (`jobs/Telemetry.tsx`) — four stat tiles: running, completed, results yielded, avg runtime.
3. **Composer** (`jobs/Composer.tsx`) — a single selection across the named pipelines and the six tools (subfinder/httpx/nuclei/nmap/dnsx/naabu). Picking a pipeline clears the tool highlight and vice versa, so only one thing is ever chosen; the tool's config is preserved across the toggle. Nothing is queued until **Queue**, and a pipeline confirms first since it queues several jobs at once.

   Two pipelines ship in `PIPELINES` (`jobs/mockData.tsx`):

   | Pipeline | Chain | For |
   |---|---|---|
   | **Attack Surface** | subfinder → dnsx → httpx → nuclei | An external surface you have to discover. Each stage feeds the next through the recon store. |
   | **Host Enumeration** | naabu → nmap → httpx | A scope you were given. These read the same scope rather than feeding each other; chaining them keeps three tools off the client's hosts at once. |

   Selecting a pipeline expands it into a **stage editor**: each stage can be included or excluded, so subfinder → httpx alone is as valid as the full chain. Order always follows the pipeline definition, so re-including a stage restores its original position rather than appending it. Stage inclusion is stored per pipeline (`Record<pipelineId, Record<toolType, boolean>>`) because httpx appears in both — excluding it from one must not touch the other. The card blurb, the summary line and the confirm dialog all read from the current selection, so none of them can advertise a chain the operator has edited away. Queue is disabled while zero stages are included.

   Excluding a middle stage is safe: the Composer posts only the included stages and the backend links `depends_on` sequentially over whatever it receives, so the survivors chain to each other rather than leaving a dangling wait.

   Target source, recurrence and saved profiles are hidden for a pipeline — stages carry their own source and config, profiles are per-tool, and `/schedules` stores a single `tool_type` so a recurring pipeline would silently drop its later stages. Preview is disabled too: it resolves one tool against one source, and later stages consume targets that do not exist until earlier ones run.

   `PIPELINES` (`jobs/mockData.tsx`) is the single definition; `JobsSection` posts the stage list the Composer hands back, so what is displayed is exactly what is queued.

   A third pipeline, **API Assessment** (httpx → `vardrgate_api_test`), needs a stored case. Selecting it — or the standalone `vardrgate` tool — shows a picker of the engagement's `authorization_test_cases`, and **Queue** stays disabled until one is chosen, since a vardrgate job without a case is a guaranteed `400`. The chosen id is injected into the vardrgate stage's config at submit. Excluding that stage drops the requirement.
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
[VardrRunner docs](https://github.com/VardrSec/VardrRunner/tree/main/docs).

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

---

## Target Architecture

Added 2026-08-12 alongside `product-vision.md`, `domain-model.md`,
`security-model.md`, and `implementation-roadmap.md`. The sections above
describe what is deployed today; this section describes what it is becoming and
which parts are already true.

### Control plane / execution plane split

```
  VardrMap (control plane)          VardrRunner (execution plane)
  ────────────────────────          ────────────────────────────
  scope, policy, assets             runs inside customer network,
  jobs, results, audit              CI, or analyst workstation
                                    resolves secrets locally
        │                                     │
        │   versioned JSON job envelope       │
        ├────────────────────────────────────►│
        │                                     │
        │   sanitized progress + results      │
        │◄────────────────────────────────────┤
        │
        └──► VardrGate (Go) — API authorization engine, one executor
             behind the contract, never a control-plane dependency
```

The control plane holds no tool-specific logic. It emits job envelopes and
consumes results. This is why VardrGate can be swapped, extended, or run
standalone without touching VardrMap.

**Already true:** VardrRunner calls `/engagements/*`, `/jobs/pending`,
`/jobs/{id}/claim`, `/jobs/{id}/events`, and `/runner/heartbeat`. Registration,
heartbeat, claim, and progress contracts substantially exist. Phase 3 versions
them and adds signing, cancellation, and capability reporting rather than
rebuilding them.

### Job envelope — derived, not invented

VardrGate already defines the execution-bounds contract in `internal/job`:

```go
type Execution struct {
    TimeoutSeconds      int   `json:"timeout_seconds,omitempty"`
    MaxResponseBytes    int64 `json:"max_response_bytes,omitempty"`
    AllowPrivateTargets bool  `json:"allow_private_targets,omitempty"`
}
```

The shared protocol derives from this rather than defining a competing shape.

**Known mismatch:** VardrGate's `Envelope.ProgramID` is `int`; VardrMap uses
string UUIDs throughout. The shared contract must use the string form, and
VardrGate's field needs widening when the adapter is built (Phase 3). Recorded
here rather than papered over.

### Secret handling across the boundary

VardrGate's `internal/secretref` resolves `${VAR}` against the local process
environment, and treats an unset variable as an error rather than an empty
string. The control plane stores the *reference*; the runner resolves the
*value* in the customer's environment. Secrets never traverse the control plane.

### Tenancy — the known structural gap

Two access models currently coexist:

- Engagement-scoped resources use `get_engagement_or_404` (`deps.py:77`) —
  owner **or** member. Correct.
- Job, schedule, and client endpoints filter on
  `owner_github_id == current_user["github_id"]` directly — owner only.

Consequences: an invited teammate cannot operate an engagement's jobs; the
runner authenticates as a user, so a team cannot share runner infrastructure;
and a firm cannot share a client record. The identity anchor is a GitHub user,
not an organization. Phase 1b converts this; see `implementation-roadmap.md`.

### Policy evaluation

Scope and authorization evaluation is centralized in `backend/policy.py` — a
pure module with no database or framework dependency, so it is exhaustively
testable. Callers pass a `PolicyInput`; it returns a `PolicyDecision` carrying
`allowed` and a stable `reason` code. `backend/enforcement.py` adapts it to the
ORM via `check()`, which returns the decision rather than raising.

It is invoked at **three** points — job creation, job claim, and the
`PATCH /jobs/{id}` transition into `running` — so the result reflects state at
the moment work starts, not just when it was queued.

Findings are **advisory**: they ride back on the response as a `warnings` array
and the job runs anyway. Only `stop_work_active` raises (`403`). See
`security-model.md` for the reason-code table and the rationale.

### Asset graph (Phase 2)

The largest remaining structural gap. Today a host exists as five unrelated
free-text columns with no foreign keys between them, and identity resolution is
string comparison. Nothing can be correlated, aggregated by asset, or diffed
over time. The relational edge-table design is specified in `domain-model.md`.
