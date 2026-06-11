# Changelog

All notable changes to VardrMap. Versions are tagged by milestone — this project does not use semver.

---

## v0.14.0 — Service discovery, atomic job claim, config validation, API key tracking (2026-06-11)

### Added
- **Service discovery** — `services` table + Alembic migration 0007; `GET/POST/DELETE /programs/{id}/services`; VardrRunner `nmap` job type: safe profile (`--top-ports N -sV --version-intensity 2 -T{0-4} --open`), parses XML output via stdlib `ElementTree`, bulk-upserts via `POST /programs/{id}/services`; `ServicesSection` in frontend Review tab
- **Atomic job claim** — `POST /jobs/{id}/claim`: atomically sets `status = "running"` only if currently `"pending"`, returns `409` if not pending; VardrRunner now uses this endpoint instead of `PATCH /jobs/{id}`
- **Per-tool config validation** — `POST /programs/{id}/jobs` rejects unknown config keys, invalid nuclei severity values, and nmap timing values outside 0–4
- **API key `last_used_at`** — stamped on every successful API key authentication; included in `GET /auth/apikeys` list response
- **nmap tool in Composer** — added to frontend `TOOLS` dict with `top_ports` and `timing` config fields
- **Services tab in Review section** — fourth tab in `ReviewSection`; `ServicesSection` shows host/port/protocol/service/product+version/state table with per-row delete

### Fixed
- **nuclei templates bug** — `",".join(cfg["templates"])` would iterate characters when `templates` was already a string (e.g. `"cves,exposures"` → `"c,v,e,s,…"`); fixed with `isinstance(raw_templates, list)` guard
- **Subfinder config UI** — removed unused `recursive`/`sources` fields from Composer (they have no effect in VardrRunner)
- **Docs enum drift** — `api.md`: scope kinds now correct (`subdomain`, `api` replacing `ip`, `other`); finding status values now correct (`candidate`, `in_progress`, `closed` replacing `accepted`, `rejected`, `informational`)

### Tests
- Backend: 114 tests (was 86); +`TestClaimJob` (6 tests), +`TestJobConfigValidation` (4 tests), +`test_nmap_tool_accepted`, +`TestListServices`/`TestBulkCreateServices`/`TestDeleteService`/`TestServicesCascade` (13 tests), +`test_last_used_at_stamped_on_use`
- Runner: 70 tests (was 58); +`test_nmap.py` (12 tests); fixed `test_client_claim_job` (now uses `POST /claim`); fixed `test_tool_version_returns_none_for_unknown_tool` (`nmap` is now valid, test uses `masscan`)

### Docs
- `docs/api.md`: services section, claim endpoint, nmap job type, corrected scope kinds and finding statuses, `last_used_at` in API key list
- `docs/architecture.md`: services table, `last_used_at` on `api_keys`, `dashboardPrefill` rename, nmap in Composer, corrected job claim flow, nmap in ALLOWED_TOOLS
- `CLAUDE.md`: atomic claim and services marked shipped; test counts updated

---

## v0.13.2 — Pin backend Python to 3.12 for Railway deploy (2026-06-10)

### Fixed
- **Railway deploy** — added `backend/.python-version` pinned to `3.12`; Nixpacks/mise was attempting to install `python@3.13.14` for which no precompiled build exists, causing deploy failures; `3.12` has a stable precompiled binary in the mise registry

### Docs
- `README.md` and `docs/development.md`: updated Python version references from 3.14 to 3.12

---

## v0.13.1 — Validation, preselect, and docs fixes (2026-06-10)

### Fixed
- **Composer preselect** — quick-action tool buttons now correctly preselect the Composer tool even when the same tool is re-selected after a manual change; `DashboardSection` now tracks a `prefillEpoch` counter that increments on every click, so `JobsSection` gives `Composer` a new `key` each time and fully resets its state
- **`EventCreate` validation** — `kind` is now constrained to a `Literal` type (`started | targets_resolved | running | uploaded | done | failed | log`); `text` is capped at 2 000 characters via `Field(max_length=2000)`; invalid inputs return `422`
- **Docs: CLAUDE.md test counts** — corrected backend (63 → 86) and runner (40 → 58) test counts
- **Docs: README** — removed stale "throughput sparkline" reference; added heartbeat command and job-events Terminal description; expanded Roadmap with atomic claim and Nmap entries
- **Docs: development.md** — corrected backend test count (84 → 86) to reflect two new validation tests

### Tests
- Added `test_invalid_kind_422` and `test_text_too_long_422` to `tests/test_job_events.py`; backend suite is now 86 tests

---

## v0.13.0 — Job events and real Terminal logs (2026-06-10)

### Added
- **`job_events` table + Alembic migration 0006** — `job_id` (FK → scan_jobs, CASCADE DELETE), `owner_github_id`, `kind`, `text`, `created_at`
- **`POST /jobs/{id}/events`** — VardrRunner posts lifecycle events (started, targets_resolved, running, uploaded, done, failed); scoped by `owner_github_id`; returns `201` with the created event
- **`GET /jobs/{id}/events`** — Frontend polls this; returns all events in chronological order; scoped by `owner_github_id`
- **VardrRunner event posting** — `_emit()` helper posts events at every lifecycle stage in `jobs run` (subfinder, httpx, and nuclei paths); errors are swallowed so a failed event never kills the job loop
- **`VardrMapClient.post_event(job_id, kind, text)`** — new API client method

### Changed
- **Terminal** — now polls `GET /jobs/{id}/events` every 3 s while the selected job is pending or running; events are mapped to colored log lines (sys/info/ok/err); stops polling when job reaches a terminal state; falls back to `job.log` (error message) when no events are available; cache is tagged with `jobId` so switching jobs never shows stale events

### Security
- Job event endpoints scoped by `get_current_user` — a user can only read/write events for jobs they own; wrong-user returns `404`, not `403`

---

## v0.12.1 — Fixes and docs cleanup (2026-06-10)

### Fixed
- **Composer tool preselect** — `initialTool` prop now re-applies after mount via `useEffect`; Dashboard quick-action buttons correctly pre-select the tool in Composer even when the Run section was already rendered
- **Frontend error toasts** — Queue, cancel, and re-queue operations now extract `detail` from the backend error response body and display it in the toast (e.g. "Failed to queue job: tool_type must be httpx, nuclei, or subfinder") instead of a generic fallback message

### Changed
- **Railway deployment config** — `backend/railway.json` now explicitly declares `builder: NIXPACKS` and `watchPatterns: ["**"]` so Railway rebuilds whenever any backend file changes
- **`docs/development.md`** — backend test count updated to 71; runner test count updated to 51; `test_runner_heartbeat.py` added to coverage table; migration chain updated to include `0005_add_runner_heartbeats`; `vardrrunner heartbeat` command documented in the setup workflow; Go install commands added for httpx/nuclei/subfinder
- **`docs/architecture.md`** — Run section description updated: Bridge entry reflects real hostname/OS/tool chips; Telemetry entry corrects "throughput sparkline" (removed in v0.11.0); seed/simulation reference replaced with accurate description of real polling and roadmap for streamed logs

---

## v0.12.0 — VardrRunner real heartbeat (2026-06-10)

### Added
- **`POST /runner/heartbeat`** — VardrRunner reports hostname, version, OS, and per-tool availability (name, `ok`, version string); upserts one row per user in the new `runner_heartbeats` table
- **`GET /runner/status`** — frontend polls this; returns `online: true` if a heartbeat arrived within the last 5 minutes, plus the runner's full details
- **`vardrrunner heartbeat`** command — explicitly send a heartbeat and print per-tool availability to the terminal
- **Auto-heartbeat in `vardrrunner jobs run`** — heartbeat is sent quietly before processing any jobs, so the Bridge goes online the moment the user starts the runner loop
- **`runner.tool_version(name)`** — runs `{tool} -version` and parses the semver (e.g. `v1.6.9`) from stdout/stderr; used by the heartbeat to report installed versions
- **`runner_heartbeats` table + Alembic migration 0005** — `owner_github_id` (unique), `hostname`, `version`, `os_info`, `tools` (JSON), `last_seen`

### Changed
- **Bridge** — runner node now shows real hostname, OS, runner version, and per-tool chips (green with version = installed; dim = missing); "connect/disconnect" button replaced by a "sync" button that triggers an immediate status re-fetch
- **JobsSection** — `loadJobs` now fires `GET /programs/{id}/jobs` and `GET /runner/status` in parallel on every poll cycle; `runnerOnline` is derived from `runnerStatus?.online` rather than a manual toggle

### Security
- Runner heartbeat endpoints scoped by `get_current_user` — a user can only read/write their own runner status; no URL parameter exposed to manipulation

---

## v0.11.0 — Scan Jobs real API integration (2026-06-09)

### Changed
- **Scan Jobs console wired to live backend** — all fake/simulated data removed from production UI:
  - Jobs loaded on mount from `GET /programs/{id}/jobs`; adaptive polling at 5 s (while active jobs exist) or 30 s (idle)
  - "Queue Job" button in Composer calls `POST /programs/{id}/jobs` and inserts the real job record
  - "Cancel" button calls `PATCH /jobs/{id}` with `status: "failed"` and `error_message: "cancelled by operator"`
  - "Re-queue" button creates a new job with the same `tool_type`, `target_source`, and `config`
- `mapToUI(ScanJob → ScanJobUI)` converts backend job records: `progress` is 0/50/100 derived from status; `log` contains only the real `error_message` if present
- **VardrRunner subfinder job dispatch fixed** — `vardrrunner jobs run` previously fell through to the nuclei branch for any non-httpx tool; subfinder jobs now resolve wildcard scope entries to root domains, run subfinder, convert plain-text output to httpx-compatible JSONL, and upload as `httpx` recon targets (matching the `vardrrunner run subfinder` behavior)
- **Simulation engine removed** — `initJobs`, `computeYield`, `logFor`, `nextId`, `RUNNER`, `THROUGHPUT`, and the `setInterval` advancement loop are no longer in the codebase
- `Bridge` — runner node simplified: shows `"local machine"` and last poll timestamp instead of fake tool version chips; `fmtAgo(lastPoll)` now reflects real API poll time
- `Telemetry` — throughput sparkline removed; fourth tile is now a plain avg-runtime stat (real average over completed jobs with recorded `durationMs`)

---

## v0.10.0 — Workflow navigation model (2026-06-09)

### Changed
- **Sidebar navigation collapsed from 11 items to 7** — sections reorganised around the bug bounty workflow:
  - **Dashboard** — mission-control landing; now includes six quick-action buttons (Run Subfinder / HTTPX / Nuclei, Import File, Add Finding, Create Report) and an inline program edit form (replaces standalone Program Profile)
  - **Scope** — unchanged
  - **Run** — renamed from "Scan Jobs"; JOBS | IMPORT tab switcher; Jobs tab = full orchestration console (Bridge, Telemetry, Composer, JobBoard, Terminal); Import tab = file upload panel (absorbs the former Imports section)
  - **Review** — new section; RECON | SCANS | MANUAL tab switcher wrapping the existing ReconSection, ScanningSection, and ManualSection components
  - **Findings** — unchanged
  - **Reports** — unchanged
  - **Settings** — unchanged
- `Section` type in `frontend/app/types.ts` narrowed to 7 values: `"dashboard" | "scope" | "run" | "review" | "findings" | "reports" | "settings"`
- Dashboard quick-action buttons navigate via `navigateToRun(tool)` / `navigate(section)` from `AppContext`; subfinder/httpx/nuclei buttons pre-select the matching tool in Composer on arrival
- **Program Profile section removed** — edit form merged into Dashboard as an always-visible panel
- **Imports section removed** — file upload logic moved into Run → Import tab

### Added
- `RunSection.tsx` — thin shell providing the Run section header + JOBS | IMPORT tab switcher; consumes `runPrefill` from AppContext and forwards `defaultTool` / tab selection on mount
- `ReviewSection.tsx` — RECON | SCANS | MANUAL tab switcher; renders sub-components with `hideHeader` to suppress duplicate section headers
- `runPrefill: { tool?, tab? } | null` AppState field + `NAVIGATE_TO_RUN` / `RUN_PREFILL_CONSUMED` reducer actions + `navigateToRun()` context helper — enables dashboard buttons to deep-link into Run with a specific tool or import tab pre-selected
- `hideHeader?: boolean` prop on `ReconSection`, `ScanningSection`, `ManualSection`, and `JobsSection` — suppresses the inner `SectionHeader` / title row when hosted inside a parent tab container
- `initialTool?: string` prop on `Composer` — initialises the tool picker state from the parent; falls back to `"nuclei"` if the value is not a valid tool id
- `defaultTool?: string` prop on `JobsSection` — passed through to `Composer` as `initialTool`

---

## v0.9.0 — Scan Jobs orchestration console (2026-06-09)

### Changed
- **Scan Jobs section redesigned** as a full orchestration console with four zones:
  - **Execution Link (Bridge)** — animated wire visualization showing VardrMap ↔ VardrRunner connection status; collapsible strip mode; auto-run toggle; runner connect/disconnect
  - **Telemetry** — four stat tiles (running, completed, results yielded, avg runtime + throughput sparkline)
  - **Composer** — tool picker (subfinder / httpx / nuclei) with per-tool config fields, target source selector with live counts, summary line, and Queue Job button
  - **Job Board + Terminal** — three switchable board views (Stream, Pipeline, Table); selecting a job opens a live terminal showing streamed log output; re-queue and cancel actions
- Jobs animate through their lifecycle (pending → running → done/failed) in the browser via a 800ms simulation engine matching the real VardrRunner execution model
- Seed data provides a realistic spread of jobs across all lifecycle states on first load
- Components extracted to `frontend/app/components/jobs/` (Bridge, Telemetry, Composer, JobBoard, Terminal, mockData)

### Added
- `ScanJobUI`, `LogLine`, `ToolDef`, `ConfigField` TypeScript types in `frontend/app/types.ts`
- CSS keyframe animations `wireFlow` and `packetRun` for the Bridge link wire

### Fixed
- Backend `POST /programs/{id}/jobs` now accepts `tool_type: "subfinder"` — the validation check previously only allowed `httpx` and `nuclei`, which would reject any subfinder job queued from the Composer

---

## v0.8.0 — PDF export, scan job queue, and subfinder (2026-06-09)

### Added
- **PDF report export** — "Export PDF" button in the Reports section generates a formatted A4 PDF client-side using jsPDF (dynamic import, no SSR issues)
- **Scan job queue** — new `scan_jobs` table and four endpoints (`POST /programs/{id}/jobs`, `GET /programs/{id}/jobs`, `GET /jobs/pending`, `PATCH /jobs/{id}`) enable the UI to queue scans and VardrRunner to poll, claim, and complete them; status flow: `pending → running → done | failed`
- **Jobs section** — new "Scan Jobs" nav item in the frontend with a job creation form (tool, target source, per-tool options) and a live job queue list with status chips and refresh button
- **VardrRunner: job queue commands** — `vardrrunner jobs list` shows pending jobs; `vardrrunner jobs run [--yes]` claims and executes all pending jobs in sequence, uploading results via existing import endpoints
- **VardrRunner: subfinder support** — `vardrrunner run subfinder --program <id>` extracts wildcard scope entries (`*.example.com`), strips the `*.` prefix, runs subfinder, and imports discovered subdomains as httpx recon targets; `subfinder` added to the tool allowlist
- **Alembic migration 0004** — `scan_jobs` table with CASCADE DELETE on `program_id`, indexed on `owner_github_id`
- **21 new backend tests** covering all four job endpoints, BOLA isolation, and status validation
- **13 new VardrRunner tests** covering subfinder arg construction, wildcard extraction, API client methods, and job queue execution
- **Context/reducer extraction** — app-wide state moved into `AppContext.tsx` + `appReducer.ts`; all section components now call `useAppContext()` instead of receiving `authFetch`/`setMessage`/`onRefresh` as props

### Added (continued)
- **`vardrrunner status`** — top-level setup/health check command; shows config file, API URL, API key, authentication result (username), program count, and per-tool PATH availability (httpx, nuclei, subfinder); prints login hint if not configured; catches HTTP errors and network failures without crashing; never prints the API key

### Changed
- VardrRunner: missing tool now marks the job `failed` with an error message instead of silently skipping it; job stays visible in the UI as failed rather than stuck as pending

### Security
- `scan_jobs` BOLA protection: `owner_github_id` checked on every job endpoint; wrong-user returns `404`, not `403`
- `subfinder` added to VardrRunner allowlist — only executes via the approved tool list, never via shell string

---

## v0.7.0 — VardrRunner v1 (2026-06-09)

### Added
- `runner/` — VardrRunner v1 local CLI, packaged as `vardrrunner` (installable via `pip install -e ./runner`)
- `vardrrunner login vardrmap` — authenticate with a VardrMap instance using a `vmap_` API key; verifies credentials before saving; warns that the config file stores the key in plaintext
- `vardrrunner whoami` — show the identity tied to the configured key
- `vardrrunner programs` — list all programs with finding and scan counts
- `vardrrunner scope <program_id>` — show in-scope and out-of-scope items
- `vardrrunner import nuclei/httpx/ffuf --program --file` — upload a tool output file directly without running the tool
- `vardrrunner run httpx --program --scope|--from-recon|--target|--targets` — run httpx locally and upload results
- `vardrrunner run nuclei --program --scope|--from-recon|--target|--targets --severity --templates` — run nuclei locally and upload results
- Dry-run confirmation prompt before every `run` command; bypass with `--yes` for automation
- `--from-recon` filters: `--limit` (default 100) and `--status-code`
- Wildcard scope entries (`*.example.com`) are skipped with a clear message instead of being passed to tools
- Raw tool output saved to `~/.vardrmap/runs/<timestamp>/` before upload; preserved if upload fails
- Config stored at `~/.vardrmap/config.json`; file permissions restricted to owner on Unix
- 17 tests covering config roundtrip, wildcard detection, target resolution, and subprocess arg-list safety

### Security
- Tool execution uses an allowlist (`httpx`, `nuclei`) — no arbitrary shell commands can be run
- `subprocess.run` is called with an argument list, never `shell=True`
- API key never printed after login

---

## v0.6.0 — Pagination (2026-06-09)

### Added
- Pagination on findings, reports, and manual tests endpoints (`limit`, `offset`, `total` in response)
- `status_code` filter on recon endpoint (used by VardrRunner `--from-recon --status-code 200`)
- Load-more button in FindingsSection and ReportsSection with remaining count display

### Changed
- Default page size: 50 for findings/reports/manual-tests (max 200); 100 for recon/scans (max 500)

---

## v0.5.0 — Migration hygiene (2026-06-09)

### Changed
- `Base.metadata.create_all()` is now guarded to only run when `ENV=development` or `ENV=test` — it no longer runs in production
- Alembic is now the sole schema authority for production; Railway runs `alembic upgrade head` before starting uvicorn on every deploy

### Added
- `backend/start.sh` — production startup script: runs `alembic upgrade head` then starts uvicorn on `$PORT`
- `backend/railway.json` — Railway deployment config pointing to `start.sh` with `ON_FAILURE` restart policy

---

## v0.4.0 — API keys and performance (2026-06-08)

### Added
- Personal API key system — generate opaque `vmap_` prefixed tokens; only the SHA-256 hash is stored; plaintext shown once in the UI
- Dual-path authentication — `get_current_user` accepts either a browser JWT or a `vmap_` API key, enabling external tool access (e.g. Burp Suite extensions)
- Settings section in the UI — generate keys with an optional label, copy-to-clipboard reveal box with "will not be shown again" warning, revoke by key
- Alembic migration `0003` — `api_keys` table with index on `github_id`, unique constraint on `key_hash`
- `created_at` column on all previously missing models (`scope_items`, `manual_tests`, `reports`, `recon_items`, `scan_items`, `import_records`)
- Alembic migration `0002` — adds nullable `created_at` to those six tables

### Changed
- `serialize_program` now returns aggregate stats only (`findings_count`, `findings_by_severity`, `findings_by_status`, `manual_tests_count`, `reports_count`) instead of eager-loading full arrays — reduces payload size on program list/fetch
- Findings, reports, and manual tests sections self-fetch their own data via `useEffect`; the program object is no longer the source of truth for those lists

### Security
- API key max of 10 per user enforced server-side
- BOLA isolation on API key list and revoke — users can only see and revoke their own keys
- `token` and `key_hash` are never returned by the list endpoint; plaintext is only in the creation response

---

## v0.3.0 — Workflow features (2026-06-07)

### Added
- Scan review workflow — status transitions (`new` → `triaged` → `accepted` / `rejected` / `ignored`), individual and bulk status update
- Report markdown preview — rendered inline before export
- Report markdown export — download as `.md` file
- Inline field editing — edit finding and report fields in place without a separate form
- Recon search — client-side filter across recon item fields
- Finding timestamps — `created_at` stored and displayed per finding
- JWT refresh — frontend re-mints the backend JWT when the Auth.js session refreshes

### Fixed
- SSL enforcement for Railway PostgreSQL (`sslmode=require` in connection string)
- JSX comment syntax bug in scan section
- `useEffect` hook dependency array warnings
- Status count query returning incorrect totals

---

## v0.2.0 — Security hardening (2026-06-05)

### Added
- Input sanitization — identifier fields (`name`, `title`, `asset`) run injection detection on raw input before any stripping; long-form fields use `bleach.clean()` to strip HTML while preserving markdown
- Security headers middleware — `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `Content-Security-Policy`, `Strict-Transport-Security` (production only)
- Audit logging — `audit_logs` table records every create/update/delete action with user, resource type, resource ID, program ID, and timestamp; no FK constraints so records survive resource deletion
- Alembic baseline migration (`0001`) — no-op snapshot of existing schema; enables incremental migrations going forward
- API query bounds — `limit`/`offset` parameters validated with `ge`/`le` constraints

### Changed
- Backend modularized into separate router files per resource

### Security
- BOLA enforcement verified — all queries filtered by `owner_github_id` derived from JWT; cross-user access returns 404, not 403, to avoid leaking resource existence
- Rate limiting raised to 200 req/min per IP (slowapi)

---

## v0.1.0 — Initial release (2026-06-01)

### Added
- Program management — create, read, update, delete bug bounty target programs with name, platform, URL, scope summary, severity guidance, and safe harbor notes
- Scope tracking — in-scope and out-of-scope items with `kind` (domain, IP, URL, etc.) and notes
- Tool import — upload ffuf, httpx, and nuclei JSON/JSONL output; parsed and stored as recon or scan items; import records kept per upload
- Recon browser — view imported httpx/ffuf results per program
- Scan browser — view nuclei results per program
- Manual testing log — title, hypothesis, payload, evidence, status per test case
- Findings tracker — title, severity, asset, status, summary, steps, impact, remediation
- Report drafting — structured vulnerability report linked to a finding; CWE, CVSS, status fields
- GitHub OAuth via Auth.js v5 — login with GitHub; session minted as short-lived HS256 JWT for backend requests
- User sync — `POST /auth/sync` upserts the user row from JWT claims on first login
- PostgreSQL backend on Railway; Next.js frontend on Vercel
