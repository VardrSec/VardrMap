# Architecture

## Product Family

VardrMap is part of the VardrSec product family. Each product is a separate deployable unit that integrates with the others via the VardrMap API and `vmap_` API keys.

| Product | Purpose | Status |
|---|---|---|
| VardrMap | Web app — stores programs, scope, findings, reports, recon, scans | Active |
| VardrRunner | Local CLI runner — runs tools on the user's machine, uploads results | v1 — `runner/` in this repo |
| VardrVault | Secrets management for VardrSec products | Planned |
| VardrScanner | Purpose-built scanning engine | Planned |

VardrRunner currently lives in `runner/` and will be extracted to a separate repo (`VardrSec/VardrRunner`) when it matures.

---

## VardrMap Overview

VardrMap is a two-service application. The frontend is a Next.js app deployed on Vercel. The backend is a FastAPI app deployed on Railway, backed by a Railway-hosted PostgreSQL database. They communicate over HTTPS; the frontend proxies all `/api/backend/*` requests to the backend URL so the browser never talks to the backend directly.

```
Browser
  │
  │  HTTPS
  ▼
Vercel (Next.js 16)
  │  proxy.ts middleware rewrites /api/backend/* → NEXT_PUBLIC_API_URL/*
  │
  │  HTTPS + Authorization: Bearer <token>
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
  created_at

programs
  id (PK)
  owner_github_id (FK → users.github_id)
  name, platform, program_url
  scope_summary, severity_guidance, safe_harbor_notes
  created_at
  → scope_items, findings, reports, manual_tests,
    recon_items, scan_items, import_records (all cascade delete)

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

scan_jobs
  id (PK)
  program_id (FK → programs.id, CASCADE DELETE, indexed)
  owner_github_id (indexed)
  tool_type ("httpx"|"nuclei"|"subfinder")
  target_source ("scope"|"recon")
  config (JSON — tool-specific options: status_code/limit for httpx; severity/templates for nuclei; recursive/sources for subfinder)
  status ("pending"|"running"|"done"|"failed")
  created_at, started_at (nullable), completed_at (nullable)
  error_message

job_logs
  id (Integer PK, autoincrement — ordering cursor for SSE)
  job_id (FK → scan_jobs.id, CASCADE DELETE, indexed)
  kind ("sys"|"info"|"out"|"ok"|"warn"|"err"|"hit")
  text (up to 4096 chars)
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
- `api_keys.key_hash` stores the SHA-256 hex digest of the plaintext token. The plaintext is never stored.
- `scan_jobs.config` is a JSON column with optional tool options. VardrRunner reads this dict when executing the job.
- `scan_jobs` are scoped to the owning user via `owner_github_id` — a user can only see/update their own jobs.
- `job_logs` stores per-line output captured from the tool's stdout/stderr. The integer `id` acts as a monotonic cursor for the SSE polling loop.

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
| Dashboard | `"dashboard"` | Program stats, 6 quick-action buttons, inline program edit form |
| Scope | `"scope"` | In-scope / out-of-scope asset management |
| Run | `"run"` | Orchestration console (Jobs tab) + file import (Import tab) |
| Review | `"review"` | Recon / Scanning / Manual Testing tab switcher |
| Findings | `"findings"` | Finding log with severity, status, promote-to-report flow |
| Reports | `"reports"` | Report drafting and PDF export |
| Settings | `"settings"` | API key management |

`RunSection` and `ReviewSection` are thin tab containers. They render child section components (`JobsSection`, `ReconSection`, etc.) with `hideHeader={true}` to suppress duplicate section headings. The `Section` type union in `frontend/app/types.ts` has exactly these 7 values.

**Deep-link navigation** — the Dashboard quick-action buttons call `navigateToRun(tool)` or `navigate(section)` from `AppContext`. `navigateToRun` dispatches `NAVIGATE_TO_RUN` which sets `state.runPrefill = { tool?, tab? }` and navigates to `"run"`. `RunSection` consumes the prefill on first render, sets the active tab and forwards `defaultTool` to `JobsSection` → `Composer`, then dispatches `RUN_PREFILL_CONSUMED`.

### Run Section — Orchestration Console

`JobsSection` (`frontend/app/components/JobsSection.tsx`) is hosted inside `RunSection`'s Jobs tab and rendered as four stacked zones:

1. **Bridge** (`jobs/Bridge.tsx`) — animated link visualization showing VardrMap ↔ VardrRunner connection status; collapses to a slim strip. Collapse state persists to `localStorage`.
2. **Telemetry** (`jobs/Telemetry.tsx`) — running/completed/yielded stats + throughput sparkline.
3. **Composer** (`jobs/Composer.tsx`) — tool picker (subfinder/httpx/nuclei) with per-tool config fields; submits new jobs.
4. **Job Board + Terminal** (`jobs/JobBoard.tsx`, `jobs/Terminal.tsx`) — three switchable board views (Stream, Pipeline, Table); a live terminal showing log output for the selected job.

The `ScanJobUI` type (`frontend/app/types.ts`) extends the API-level `ScanJob` with UI-only fields (`progress`, `yield`, `yieldKind`, `durationMs`, `log[]`). Job polling and SSE log streaming are fully wired: the frontend opens a fetch-based SSE connection to `GET /jobs/{id}/logs/stream` for selected pending/running jobs, accumulating `LogLine` objects in `jobLogsRef` and pushing them into the Terminal component in real time.

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
runner/ (Python CLI)
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

**Key design constraints:**
- Tool execution uses an allowlist (`ALLOWED_TOOLS` in `runner.py`) — `httpx`, `nuclei`, and `subfinder`
- `subprocess.run` is always called with an argument list, never `shell=True`
- Wildcard scope entries (`*.example.com`) are skipped by `run httpx/nuclei`; use `vardrrunner run subfinder --program <id>` to enumerate subdomains first, then re-run against recon results
- Config at `~/.vardrmap/config.json` stores the `vmap_` API key in plaintext — documented clearly and file permissions restricted on Unix
- Raw outputs are always saved locally before upload; if upload fails, the data is not lost

**Target sources for `run` commands:**

| Flag | Source |
|---|---|
| `--scope` | In-scope items from `GET /programs/{id}` (wildcards skipped) |
| `--from-recon` | Live recon items from `GET /programs/{id}/recon` with optional `--limit` and `--status-code` filters |
| `--target <url>` | Single inline target |
| `--targets <file>` | Local plaintext file, one target per line |

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
runner/
  │  1. GET /jobs/pending  — fetch pending jobs for this user
  │  2. PATCH /jobs/{id}   — status = "running"  (claim the job)
  │  3. resolve targets (same logic as manual run commands)
  │  4. execute tool locally via subprocess
  │  5. upload results via POST /programs/{id}/imports
  │  6. PATCH /jobs/{id}   — status = "done" | "failed"
  ▼
VardrMap backend — results stored; job status visible in Jobs section
```

If the required tool is not on PATH, the job is immediately marked `failed` with an error message — it does not stay stuck as `pending`.
