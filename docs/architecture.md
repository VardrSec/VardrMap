# Architecture

## Product Family

VardrMap is part of the VardrSec product family. Each product is a separate deployable unit that integrates with the others via the VardrMap API and `vmap_` API keys.

| Product | Purpose | Status |
|---|---|---|
| VardrMap | Web app — stores programs, scope, findings, reports, recon, scans | Active |
| VardrRunner | Local CLI runner — runs tools on the user's machine, uploads results | Separate repo: [VardrSec/VardrRunner](https://github.com/VardrSec/VardrRunner) |
| VardrVault | Secrets management for VardrSec products | Planned |
| VardrScanner | Purpose-built scanning engine | Planned |

VardrRunner is distributed from [PyPI](https://pypi.org/project/vardrrunner/)
(`pipx install vardrrunner`) and developed in its own repository,
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

Local development still uses `create_all` for convenience. Fresh production
databases are created by the frozen `0001baseline` schema and the incremental
Alembic chain; an already-versioned database skips that baseline. Unstamped,
nonempty databases are refused until their actual schema revision is identified.
Default tests rebuild SQLite; CI also exercises migrated PostgreSQL and the full
backend suite on PostgreSQL. Application and Alembic connections consistently use
UTC because existing timestamp columns store naive UTC values. This connection
policy does not reinterpret or rewrite previously stored timestamps.

---

## Authentication Flow

There are two accepted token types. Both arrive on the `Authorization: Bearer <token>` header.

### Browser JWT (normal login)

1. User clicks "Sign in with GitHub"
2. Auth.js v5 completes the GitHub OAuth flow and mints a session
3. The client-side `authFetch` helper in `AppContext.tsx` uses the Auth.js session's `backendToken` and calls the backend directly
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

Most primary keys are UUID strings; `User.github_id` is the GitHub identity key.

The current ORM inventory below includes implemented tenancy, assets, evidence,
test cases and deliverables. SQL constraints and column types are defined in
`backend/models.py`; persisted schema upgrades are defined by Alembic.

| Model / table | Columns |
|---|---|
| `User` / `users` | `github_id`, `username`, `email`, `webhook_url`, `notify_min_severity`, `created_at` |
| `Organization` / `organizations` | `id`, `name`, `personal_for_github_id`, `created_at` |
| `OrganizationMember` / `organization_members` | `id`, `org_id`, `github_id`, `role`, `created_at` |
| `Asset` / `assets` | `id`, `program_id`, `canonical_key`, `asset_type`, `label`, `hostname`, `ip`, `port`, `scheme`, `environment`, `criticality`, `exposure`, `owner_note`, `tags`, `source`, `confidence`, `first_seen_at`, `last_seen_at`, `created_at` |
| `AssetRelationship` / `asset_relationships` | `id`, `program_id`, `src_asset_id`, `dst_asset_id`, `relationship`, `source`, `confidence`, `first_seen_at`, `last_seen_at`, `created_at` |
| `Client` / `clients` | `id`, `owner_github_id`, `org_id`, `name`, `contact_name`, `contact_email`, `notes`, `created_at` |
| `Engagement` / `programs` | `id`, `owner_github_id`, `name`, `platform`, `program_url`, `scope_summary`, `severity_guidance`, `safe_harbor_notes`, `client_id`, `org_id`, `engagement_type`, `engagement_status`, `starts_at`, `ends_at`, `stop_work_at`, `stop_work_reason`, `max_request_rate`, `created_at` |
| `Authorization` / `authorizations` | `id`, `program_id`, `owner_github_id`, `permits`, `authorized_by`, `authorized_at`, `reference`, `window_start`, `window_end`, `status`, `notes`, `created_at` |
| `ScopeItem` / `scope_items` | `id`, `program_id`, `scope_type`, `value`, `kind`, `notes`, `max_severity`, `created_at` |
| `ManualTest` / `manual_tests` | `id`, `program_id`, `title`, `hypothesis`, `payload`, `evidence`, `status`, `created_at` |
| `Finding` / `findings` | `id`, `program_id`, `title`, `severity`, `asset`, `asset_id`, `status`, `summary`, `steps`, `impact`, `remediation`, `created_at` |
| `Report` / `reports` | `id`, `program_id`, `finding_id`, `title`, `summary`, `steps`, `impact`, `remediation`, `cwe`, `cvss`, `status`, `created_at` |
| `ReconItem` / `recon_items` | `id`, `program_id`, `source`, `url`, `path`, `host`, `title`, `status_code`, `webserver`, `port`, `tech`, `content_type`, `length`, `words`, `lines`, `notes`, `asset_id`, `first_seen_at`, `job_id`, `created_at` |
| `ScanItem` / `scan_items` | `id`, `program_id`, `source`, `template_id`, `title`, `severity`, `asset`, `matched_at`, `type`, `description`, `status`, `cwe`, `cvss`, `detection_method`, `payload`, `match_evidence`, `confidence`, `asset_id`, `job_id`, `created_at` |
| `ImportRecord` / `import_records` | `id`, `program_id`, `tool_type`, `filename`, `imported_count`, `job_id`, `created_at` |
| `Evidence` / `evidence` | `id`, `program_id`, `finding_id`, `asset_id`, `kind`, `title`, `body`, `content_hash`, `collector`, `source`, `sensitivity`, `retention`, `redacted`, `collected_at`, `created_at` |
| `ApiEndpoint` / `api_endpoints` | `id`, `program_id`, `asset_id`, `method`, `scheme`, `host`, `port`, `path_template`, `canonical_key`, `source`, `notes`, `observation_count`, `first_seen_at`, `last_seen_at` |
| `ApiExchange` / `api_exchanges` | `id`, `program_id`, `endpoint_id`, `source_tool`, `identity_label`, `request_headers`, `request_body`, `response_headers`, `response_body`, `request_hash`, `response_hash`, `response_status`, `response_length`, `response_mime`, `response_time_ms`, `parameter_names`, `note`, `captured_at`, `created_at` |
| `AuditLog` / `audit_logs` | `id`, `github_id`, `action`, `resource_type`, `resource_id`, `program_id`, `reason`, `detail`, `timestamp` |
| `ScanJob` / `scan_jobs` | `id`, `program_id`, `owner_github_id`, `tool_type`, `target_source`, `config`, `status`, `depends_on`, `created_at`, `started_at`, `completed_at`, `error_message` |
| `JobResultReceipt` / `job_result_receipts` | `id`, `job_id`, `payload_hash`, `scan_items_created`, `evidence_created`, `created_at` |
| `RunnerHeartbeat` / `runner_heartbeats` | `id`, `owner_github_id`, `hostname`, `version`, `os_info`, `tools`, `last_seen` |
| `JobEvent` / `job_events` | `id`, `job_id`, `owner_github_id`, `kind`, `text`, `created_at` |
| `ApiKey` / `api_keys` | `id`, `github_id`, `key_hash`, `label`, `scope`, `created_at`, `last_used_at` |
| `Service` / `services` | `id`, `program_id`, `owner_github_id`, `host`, `port`, `protocol`, `service_name`, `product`, `version`, `state`, `source`, `created_at`, `asset_id`, `last_scanned_at` |
| `RadarProgram` / `radar_programs` | `id`, `owner_github_id`, `platform`, `platform_id`, `name`, `url`, `max_payout`, `is_new`, `discovered_at`, `last_fetched_at` |
| `EngagementMember` / `program_members` | `id`, `program_id`, `owner_github_id`, `member_github_id`, `role`, `invited_at` |
| `ScanProfile` / `scan_profiles` | `id`, `program_id`, `owner_github_id`, `name`, `tool_type`, `target_source`, `config`, `created_at` |
| `AuthorizationTestCase` / `authorization_test_cases` | `id`, `program_id`, `owner_github_id`, `name`, `test_case_id`, `description`, `spec`, `created_at`, `updated_at` |
| `JobResultLink` / `job_result_links` | `id`, `job_id`, `recon_id`, `scan_id`, `service_id` |
| `FindingActivity` / `finding_activities` | `id`, `program_id`, `finding_id`, `kind`, `outcome`, `notes`, `actor`, `snapshot`, `evidence`, `created_at` |
| `EngagementDeliverable` / `engagement_deliverables` | `id`, `program_id`, `title`, `latest_revision`, `created_at` |
| `DeliverableRevision` / `deliverable_revisions` | `id`, `deliverable_id`, `revision`, `status`, `snapshot`, `markdown`, `content_hash`, `actor`, `created_at` |

**Notes:**
- `Report.finding_id` is a soft reference — no FK constraint. Reports can exist without a linked finding.
- `AuditLog` has no FK constraints so records are never deleted when users or programs are removed.
- `api_keys.key_hash` stores the SHA-256 hex digest of the plaintext token. The plaintext is never stored. `last_used_at` is stamped on every successful API key authentication. `scope` restricts runner-scoped keys to jobs/imports/heartbeat endpoints — all other endpoints return `403` for runner keys.
- `recon_items.first_seen_at` is set once when an item is first imported and never overwritten. Dedup key is `(program_id, source, url)`: re-importing the same URL produces `new_count: 0` with no duplicate row.
- `program_members` grant collaborators access to a program's resources, with two roles: **`member`** (read + write) and **`viewer`** (read-only). Only the owner can manage members and delete/PATCH the program itself. `GET /programs` returns both owned programs and programs where the user is a member.
- **Viewer enforcement:** every program-scoped write endpoint (create/update/delete of findings, reports, manual tests, scans, scan profiles, services, scope, imports, jobs, pipelines) calls `require_member_write` after `get_engagement_or_404`, which raises `403` for a viewer-role member. The guard fires before any resource lookup, so a viewer gets `403` even for a non-existent target id. Owners always pass; runner-scoped API keys resolve to the owner and therefore also pass (so uploads/heartbeats are unaffected). AI actions (`findings/{id}/suggest`, `scans/triage`) are gated too, since they incur cost. Read (`GET`) endpoints remain open to viewers.
- `scan_jobs.config` is a JSON column with optional tool options. VardrRunner reads this dict when executing the job. Unknown config keys are rejected at creation time.
- `scan_jobs` are scoped through engagement access, including organization membership and invitations; viewers cannot mutate jobs. Claiming a job uses `POST /jobs/{id}/claim` which atomically sets `status = "running"` only if currently `"pending"`, returning 409 otherwise.
- `services` rows are bulk-upserted on `(host, port, protocol)` — repeated nmap scans update metadata rather than creating duplicates. `last_scanned_at` is stamped on both insert and update so freshness is always visible.
- `radar_programs` are upserted per user on `(owner_github_id, platform, platform_id)`. New programs land with `is_new = "1"` so the Overview Radar widget can badge them; `GET /radar` marks all returned rows as seen.
- Deleting a `scan_job` (via `DELETE /jobs/{id}`) also deletes all its `job_events` via CASCADE.
- `runner_heartbeats` is upserted per `(owner_github_id, hostname)` so multiple machines (laptop + VPS) report independently. VardrRunner calls `POST /runner/heartbeat` at the start of `jobs run` and via `vardrrunner heartbeat`; it runs only when invoked, so a runner nobody has run in 5 minutes shows offline, as does one in a `jobs run` that has lasted longer than that. The frontend polls `GET /runner/status` which returns all runners and derives per-runner `online: true` if `last_seen` is within 5 minutes. Rate-limited to 60/min.
- `users.webhook_url` (stored plaintext — it must be usable, unlike hashed API keys; only ever returned to its owner) and `users.notify_min_severity` drive outbound notifications, sent via FastAPI BackgroundTasks so webhook latency never delays API responses. URLs are validated against an SSRF guard (HTTPS only, no localhost/private/link-local targets).
- `job_events` are appended by VardrRunner via `POST /jobs/{id}/events` at each lifecycle stage. The frontend Terminal polls `GET /jobs/{id}/events` (3 s interval while job is pending/running, stops on terminal state). Events cascade-delete with their parent job. Rate-limited to 600/min.
- **Pipelines** (`POST /programs/{id}/pipelines`) create an ordered chain of `scan_jobs` linked by `depends_on`. A dependent stage is withheld from `GET /jobs/pending` until its parent is `done`; each `vardrrunner jobs run` picks up whichever stages are ready. If a parent `failed`, `GET /jobs/pending` auto-fails the dependent stage so it never hangs. The endpoint accepts any valid ordered chain. The UI offers named chains from `PIPELINES` (`frontend/app/components/jobs/mockData.tsx`) — Attack Surface (subfinder → dnsx → httpx → nuclei), Host Enumeration (naabu → nmap → httpx), Content Discovery (subfinder → httpx → katana → gau), and API Assessment — with each stage individually includable, so it may post any ordered subset. `depends_on` is linked sequentially over whatever arrives, so a subset still chains correctly.
- **Provenance:** `recon_items.job_id` and `scan_items.job_id` record which `scan_job` *created* each row (from the optional `job_id` on `POST /imports`; null for manual uploads). Because deduplication means a later job often re-observes a row an earlier job created, `job_result_links` additionally records every row a job *observed* - recon, scan and service - so "what did this run find" stays answerable after enrichment or de-duplication. The `job_id` is validated against the engagement's own jobs (`404` otherwise): it is a real foreign key, and an unvalidated one could link another engagement's job. `GET /programs/{id}/recon?job_id=`, `.../scans?job_id=` and `.../services?job_id=` filter by it, so the Terminal can deep-link from a finished job to exactly the rows it yielded. VardrRunner passes the job id on every upload. (`scans` only honoured the creator stamp until v0.41.0, so a deduplicated re-scan looked as though it had found nothing; it now matches recon and services.)
- **Finding history:** every finding create and update appends a `finding_activities` snapshot (the first update of a pre-existing finding records a `baseline` of its prior state, under a row lock). Remediation notes and retests are further activity kinds; a retest requires an outcome. Snapshots and notes pass through the secret redactor before storage, and evidence is referenced by title and SHA-256 so its integrity survives later retention. History is deleted with its finding (the audit log retains that it happened).
- **Deliverables:** `engagement_deliverables` / `deliverable_revisions` are the client-facing report. A revision freezes the scope, authorizations, selected findings and evidence and retest history at save time, with rendered Markdown and its SHA-256; only `status` changes afterwards. Saves use optimistic concurrency (`base_revision`, `409` if stale) and the snapshot is redacted and capped at 4 MiB. Evidence is rendered as indented blocks so target-controlled text cannot escape the report, and the UI renders the Markdown without raw HTML, with images replaced by text and links filtered.
- **Case authoring:** `POST /test-cases/preview` drafts VardrGate cases from observed API operations or an OpenAPI document and stores nothing; `POST /test-cases/reviewed` saves them only with an explicit `reviewed: true`. Drafts never copy credentials or example values, never fetch `$ref`s, and start with every access decision `skip`, because observed responses do not establish who *should* have access.
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
3. **Composer** (`jobs/Composer.tsx`) — a single selection across the named pipelines and the eleven tools (subfinder/httpx/nuclei/nmap/dnsx/naabu/katana/gau/ffuf/dalfox/vardrgate_api_test). Picking a pipeline clears the tool highlight and vice versa, so only one thing is ever chosen; the tool's config is preserved across the toggle. Nothing is queued until **Queue**, and a pipeline confirms first since it queues several jobs at once.

   Four pipelines ship in `PIPELINES` (`jobs/mockData.tsx`):

   | Pipeline | Chain | For |
   |---|---|---|
   | **Attack Surface** | subfinder → dnsx → httpx → nuclei | An external surface you have to discover. Each stage feeds the next through the recon store. |
   | **Host Enumeration** | naabu → nmap → httpx | A scope you were given; each stage uses scope. |
   | **Content Discovery** | subfinder → httpx → katana → gau | Find live hosts, crawl them and import archived URLs. |
   | **API Assessment** | httpx → vardrgate_api_test | Confirm reachability, then execute a selected stored authorization test case. |

   Selecting a pipeline expands it into a **stage editor**: each stage can be included or excluded, so subfinder → httpx alone is as valid as the full chain. Order always follows the pipeline definition, so re-including a stage restores its original position rather than appending it. Stage inclusion is stored per pipeline (`Record<pipelineId, Record<toolType, boolean>>`) because httpx appears in both — excluding it from one must not touch the other. The card blurb, the summary line and the confirm dialog all read from the current selection, so none of them can advertise a chain the operator has edited away. Queue is disabled while zero stages are included.

   Excluding a middle stage is safe: the Composer posts only the included stages and the backend links `depends_on` sequentially over whatever it receives, so the survivors chain to each other rather than leaving a dangling wait.

   Target source and saved profiles are hidden for a pipeline — stages carry their own source and config, and profiles are per-tool. Preview is disabled too: it resolves one tool against one source, and later stages consume targets that do not exist until earlier ones run.

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
5. Items are passed to the tool-specific parser (`parse_ffuf`, `parse_httpx`, `parse_nuclei`, `parse_katana`, `parse_gau`, `parse_dalfox`). URL-shaped recon (ffuf, katana, gau) is deduplicated per engagement and source, against stored rows and within the upload. **dalfox scan items are deduplicated too** — on the query-less URL, the injection context and parameter (`template_id`), and the tier — because a re-scan re-reports every match it still finds; the payload and PoC URL are excluded from the key since both carry a per-run marker class. Deduplicated matches still get a `job_result_links` row, so a re-scan's observations remain visible. nuclei is **not** deduplicated, which is pre-existing behaviour. `parse_ffuf` reads ffuf's own keys (`url`, `input.FUZZ`, `status`, `content-type`), so both a raw `ffuf -of json` report and the JSONL VardrRunner uploads import identically
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

The UI queues jobs; VardrRunner executes them when the operator runs `vardrrunner jobs run` on their machine. Nothing runs unattended: there are no recurring scans and no background worker. Queuing happens in the browser, execution on the user's machine.

**Request controls.** The Composer's Request Controls set a requests-per-second `rate` (httpx, nuclei, katana, ffuf) and custom `headers` (those plus dalfox), e.g. a program's rate limit and identification header. They persist across tool and pipeline changes and are applied to every pipeline stage that accepts them. `lib/requestControls.ts` validates them with the backend's rules, and the rate field shows and enforces the engagement's `max_request_rate`.

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

The control plane validates tool configuration and imports tool-specific results;
execution lives in VardrRunner and VardrGate. Runner registration, heartbeat,
claim and progress contracts are implemented. Gate integration uses string
engagement identifiers; the earlier integer identifier mismatch is resolved.
Signed/versioned contracts and running-process cancellation remain future work.

### Secret handling across the boundary

VardrGate's `internal/secretref` resolves `${VAR}` against the local process
environment, and treats an unset variable as an error rather than an empty
string. Stored identity credentials use `value_env`/`value_keychain` references;
the runner resolves the value in the customer's environment. This guard does not
prove arbitrary request bodies, URLs or evidence are free of embedded secrets.

### Tenancy

`deps.engagement_access()` combines direct ownership, organization membership
and engagement invitations. Job access follows the engagement.
Clients allow direct ownership or organization membership; viewers cannot mutate them.
API keys and runner heartbeats remain user-bound, so organization-bound execution
credentials need a separate design.

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

### Asset graph

Assets and relationship edges are implemented. Importers and findings link hosts
to canonical assets, and evidence can reference both assets and findings.
See [domain model](domain-model.md) for the implemented relationship boundaries.

# Evidence association

Evidence retains its existing nullable `finding_id` relationship. A reviewed
link operation can associate engagement-level scan evidence with a finding in
the same engagement. It preserves the row ID, body hash and execution provenance;
it does not create a copy. Evidence already linked to another finding cannot be
reassigned, preserving finding history. New links require member-level write
access and produce an audit entry. No schema migration is needed.

## Security audit amendments (2026-10-11)

Signed JWTs require `exp`, `sub`, `aud` and `iss` claims. Shared client PATCH/DELETE
requires direct ownership or organization member-level write access; organization
viewers receive 403, unrelated users 404. AI suggestion/triage inputs are redacted
before provider calls and provider failures return generic 502 details. Redaction
is heuristic; AI output remains a draft requiring human review.
Webhook delivery connects to an approved resolved address while preserving the
original HTTP Host and TLS identity. It disables environment proxies and redirects,
rejects malformed/credential-bearing URLs and logs error types rather than secret URLs.
Imports enforce the existing size cap with a bounded read.

## Text preservation and deletion ordering

New sanitized text preserves literal ampersands and entity syntax (`&`, `&amp;`,
`&#38;`) instead of HTML-encoding or collapsing them. Existing rules still remove
HTML tags, remove null bytes and reject injection patterns in identifier fields.
Render the result as text or through the existing safe Markdown renderer, never
by inserting raw HTML. Existing stored text is not decoded or rewritten.

Observation links declare their recon/scan/service relationships so the ORM
orders their deletion before deleting observed targets. Job deletion continues
to remove its links while retaining observations. No database migration is needed.

## Gate assessment records and shared guidance

`ScanJob.case_snapshot` (nullable JSON) freezes the unresolved reviewed spec in the
atomic claim transition; `ScanJob.assessment` (nullable JSON) is computed on upload
against this snapshot and stored in the same transaction as evidence, candidates
and the idempotency receipt. Lifecycle `done` means execution finished. Assessment
`conclusive` means the declared identities have definite reported outcomes and a
working legitimate baseline, not that the API is secure or the candidates verified.

Runner adds a canonical SHA-256 of its unresolved case to the retained result
artifact. A conflicting hash is refused; a missing binding remains inconclusive.
This is correlation, not a signed attestation of an uncompromised runner. Historical
assessments remain null. Migration 0027 is additive, with one successor to 0026.

Evidence has nullable indexed `job_id`, `case_id`, `identity_id`, plus `case_ref`,
`observed_outcome` and `expected_decision`. Job/case FKs use SET NULL so deleting
one preserves retained proof and logical identity metadata. Engagement/finding
retention rules remain unchanged. The stored evidence body and hash include the
case binding signal; report revisions and finding activity snapshot provenance.
Manual evidence cannot set execution metadata. Queries remain engagement-scoped.

Optional `identities[].preflight` lives in the reviewed JSON spec and its claim-time
snapshot. Gate checks session metadata after setup and before authorization traffic;
Runner's CLI guard rejects older Gate binaries and retains exit-3 diagnostics for
upload before marking the job failed. Crash recovery preserves failed finalization.
Map computes `assessment.preflight` against the same snapshot and stores safe
per-identity probe evidence with `phase: identity_preflight`; probes never establish
resource decisions. This uses existing JSON/evidence fields and needs no migration.
Raw session responses and credentials remain on the operator's machine. See
[identity preflight](identity-preflight.md) for the compatibility boundary.

`backend/api_playbooks.json` is the sole original v1.0 guidance catalog, validated
at startup by `playbooks.py` (extra fields forbidden, unique ids). Full-scope read
endpoints serve summaries and individual guides. Map's case builder and Runner
MCP read that same catalog on demand; no duplicate data bundle, progress fields,
automatic permission decisions or automatic human sign-off are introduced.
