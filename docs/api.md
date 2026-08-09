# API Reference

All endpoints require `Authorization: Bearer <token>` unless noted otherwise. The token is either a browser JWT (minted by the frontend after GitHub OAuth) or a personal API key with the `vmap_` prefix. See [architecture.md](architecture.md) for how each token type is resolved.

All responses are JSON. Timestamps are ISO 8601 UTC strings.

**Base URL (production):** set by `NEXT_PUBLIC_API_URL` — the frontend proxies `/api/backend/*` to this value.

---

## Health

### `GET /`
Returns API status and current environment. No auth required.

**Response**
```json
{ "message": "VardrMap API is running", "environment": "production" }
```

### `GET /health`
Health check. No auth required.

**Response**
```json
{ "status": "ok", "environment": "production" }
```

---

## User / Auth

### `POST /auth/sync`
Upserts the user row from the JWT claims. Call this once after login to ensure the `users` table reflects the current GitHub profile. Returns the stored user record.

**Response**
```json
{
  "github_id": "12345678",
  "username": "jorge-aquino",
  "email": "user@example.com",
  "created_at": "2026-06-01T12:00:00"
}
```

### `GET /me`
Returns the identity resolved from the current token. Useful for verifying that a token (JWT or API key) is valid.

**Response**
```json
{
  "github_id": "12345678",
  "username": "jorge-aquino",
  "email": "user@example.com"
}
```

---

## API Keys

### `GET /auth/apikeys`
List the current user's API keys. Does not return the token or hash — only metadata.

**Response**
```json
{
  "keys": [
    { "id": "<uuid>", "label": "Burp Suite", "scope": "full", "created_at": "2026-06-08T10:00:00", "last_used_at": "2026-06-11T09:00:00" }
  ]
}
```

### `POST /auth/apikeys`
Generate a new API key. The plaintext token is returned **once** in this response and is not stored. Maximum 10 keys per user.

**Request body**
```json
{ "label": "Burp Suite", "scope": "runner" }
```
`label` is optional (max 100 chars). `scope` is `"full"` (default) or `"runner"`.

- **`full`** — unrestricted; can call any endpoint
- **`runner`** — restricted to job polling, imports, and heartbeat; safe to deploy on a VPS running VardrRunner

**Response**
```json
{
  "id": "<uuid>",
  "label": "Burp Suite",
  "scope": "full",
  "created_at": "2026-06-08T10:00:00",
  "token": "vmap_<43 random chars>"
}
```

**Errors**
- `400` — at or above the 10-key limit

### `DELETE /auth/apikeys/{key_id}`
Revoke an API key. Returns 404 if the key does not belong to the current user.

**Response**
```json
{ "message": "API key revoked" }
```

---

## Engagements

### `GET /engagements`
List all engagements where the current user is the owner **or** an invited member. Each engagement includes aggregate stats — not full arrays of findings, reports, or manual tests.

**Response**
```json
{
  "engagements": [ <program_object>, ... ]
}
```

### `POST /engagements`
Create a new engagement.

**Request body**
```json
{
  "name": "HackerOne - Acme Corp",
  "platform": "HackerOne",
  "program_url": "https://hackerone.com/acme",
  "scope_summary": "Web and mobile apps",
  "severity_guidance": "P1 for auth bypass, P2 for stored XSS",
  "safe_harbor_notes": "No physical testing"
}
```
Only `name` is required. All other fields default to empty string.

**Response:** full engagement object

### `GET /engagements/{program_id}`
Get a single engagement by ID. Returns 404 if it does not belong to the current user.

**Response:** full engagement object

### `PATCH /engagements/{program_id}`
Update engagement fields. Only fields included in the request body are changed.

**Request body:** any subset of `POST /engagements` fields

**Response:** updated engagement object

### `GET /engagements/{program_id}/stats`
Lightweight aggregate stats for a engagement — used by the Dashboard stat cards. Returns counts and breakdowns without serializing full objects. Much cheaper than `GET /engagements/{id}` when only counts are needed.

**Response**
```json
{
  "recon_count": 120,
  "scans_count": 55,
  "findings_count": 7,
  "manual_tests_count": 3,
  "reports_count": 3,
  "findings_by_severity": { "critical": 1, "high": 2, "medium": 3, "low": 1, "info": 0 }
}
```

### `DELETE /engagements/{program_id}`
Delete a engagement. Cascades to all child records (scope, findings, reports, manual tests, recon, scans, imports).

**Response**
```json
{ "message": "Engagement deleted" }
```

**Engagement object shape**
```json
{
  "id": "<uuid>",
  "name": "HackerOne - Acme Corp",
  "platform": "HackerOne",
  "program_url": "https://hackerone.com/acme",
  "scope_summary": "...",
  "severity_guidance": "...",
  "safe_harbor_notes": "...",
  "scope": {
    "in":  [ { "id": "<uuid>", "value": "*.acme.com", "kind": "domain", "notes": "" } ],
    "out": [ { "id": "<uuid>", "value": "blog.acme.com", "kind": "domain", "notes": "" } ]
  },
  "imports": [
    { "id": "<uuid>", "tool_type": "nuclei", "filename": "redacted", "imported_count": 42 }
  ],
  "recon_count": 120,
  "scans_count": 55,
  "manual_tests_count": 3,
  "findings_count": 7,
  "findings_by_severity": { "critical": 1, "high": 2, "medium": 3, "low": 1, "info": 0 },
  "findings_by_status":   { "new": 4, "triaged": 2, "accepted": 1, "rejected": 0 },
  "reports_count": 3,
  "services_count": 8,
  "my_role": "owner"
}
```

`my_role` is the calling user's role in this engagement: `"owner"` (the engagement owner), `"member"` (invited collaborator with write access), or `"viewer"` (invited collaborator with read-only access). Viewers receive `403` on mutation routes (POST/DELETE findings, reports, scope items).

---

## Scope

### `POST /engagements/{program_id}/scope/in`
Add an in-scope item.

**Request body**
```json
{ "value": "*.acme.com", "kind": "domain", "notes": "" }
```
`kind` values: `domain`, `subdomain`, `url`, `cidr`, `api`, `mobile`. `notes` is optional.

**Response:** scope item object

### `POST /engagements/{program_id}/scope/out`
Add an out-of-scope item. Same request body as above.

**Response:** scope item object

### `DELETE /engagements/{program_id}/scope/{scope_type}/{item_id}`
Remove a scope item. `scope_type` must be `in` or `out`.

**Response**
```json
{ "message": "Scope item deleted" }
```

---

## Findings

### `GET /engagements/{program_id}/findings`
List findings for a engagement, ordered by `created_at` descending.

**Query parameters**
| Parameter | Default | Constraints | Description |
|---|---|---|---|
| `limit` | 50 | 1–200 | Max items to return |
| `offset` | 0 | ≥0 | Number of items to skip |
| `search` | (none) | — | `ILIKE` filter across title and asset |
| `severity` | (none) | — | Exact match: `critical`, `high`, `medium`, `low`, `info` |

**Response**
```json
{
  "findings": [ { "id": "<uuid>", "title": "...", "severity": "high", "asset": "app.acme.com", "status": "triaged", "summary": "...", "steps": "...", "impact": "...", "remediation": "...", "created_at": "2026-06-05T09:00:00" } ],
  "total": 42,
  "offset": 0,
  "limit": 50
}
```

### `POST /engagements/{program_id}/findings`
Create a finding.

**Request body**
```json
{
  "title": "Stored XSS in profile bio",
  "severity": "high",
  "asset": "app.acme.com",
  "status": "new",
  "summary": "...",
  "steps": "...",
  "impact": "...",
  "remediation": "..."
}
```
`title` is required. `severity` values: `critical`, `high`, `medium`, `low`, `info`. `status` values: `new`, `candidate`, `triaged`, `in_progress`, `closed`.

**Response:** finding object

### `PATCH /engagements/{program_id}/findings/{finding_id}`
Update a finding. Only fields present in the body are changed.

**Response:** updated finding object

### `DELETE /engagements/{program_id}/findings/{finding_id}`
Delete a finding.

**Response**
```json
{ "message": "Finding deleted" }
```

### `POST /engagements/{program_id}/findings/{finding_id}/suggest`
Ask Claude AI to draft CVSS score, impact statement, and remediation for a finding.

Requires `ANTHROPIC_API_KEY` to be set on the server. Returns `503` if the key is absent.

**Response**
```json
{ "cvss": "7.5 (High)", "impact": "Attackers can exfiltrate sensitive data...", "remediation": "Use parameterized queries..." }
```

**Error codes:** `401` unauthorized / wrong user, `404` finding not found, `503` API key not configured, `502` AI returned non-JSON or request failed.

**Rate limit:** shares the global 200/min default.

---

## Reports

### `GET /engagements/{program_id}/reports`
List reports for a engagement, ordered by `created_at` descending.

**Query parameters**
| Parameter | Default | Constraints | Description |
|---|---|---|---|
| `limit` | 50 | 1–200 | Max items to return |
| `offset` | 0 | ≥0 | Number of items to skip |

**Response**
```json
{
  "reports": [ { "id": "<uuid>", "finding_id": "<uuid or empty>", "title": "...", "summary": "...", "steps": "...", "impact": "...", "remediation": "...", "cwe": "CWE-79", "cvss": "7.5", "status": "draft", "created_at": "2026-06-05T09:00:00" } ],
  "total": 10,
  "offset": 0,
  "limit": 50
}
```

### `POST /engagements/{program_id}/reports`
Create a report.

**Request body**
```json
{
  "title": "Stored XSS in profile bio",
  "finding_id": "<uuid>",
  "summary": "...",
  "steps": "...",
  "impact": "...",
  "remediation": "...",
  "cwe": "CWE-79",
  "cvss": "7.5",
  "status": "draft"
}
```
`title` is required. `finding_id` is optional — reports can exist without a linked finding. `status` values: `draft`, `submitted`, `accepted`, `rejected`.

**Response:** report object

### `PATCH /engagements/{program_id}/reports/{report_id}`
Update a report. Only fields present in the body are changed.

**Response:** updated report object

### `DELETE /engagements/{program_id}/reports/{report_id}`
Delete a report.

**Response**
```json
{ "message": "Report deleted" }
```

---

## Manual Tests

### `GET /engagements/{program_id}/manual-tests`
List all manual test cases for a engagement, ordered by `created_at` descending.

**Response**
```json
{
  "manual_tests": [
    {
      "id": "<uuid>",
      "title": "IDOR on /api/users/{id}",
      "hypothesis": "Endpoint does not validate ownership",
      "payload": "GET /api/users/999 with own JWT",
      "evidence": "Returned another user's profile",
      "status": "validated"
    }
  ]
}
```

### `POST /engagements/{program_id}/manual-tests`
Create a manual test case.

**Request body**
```json
{
  "title": "IDOR on /api/users/{id}",
  "hypothesis": "...",
  "payload": "...",
  "evidence": "...",
  "status": "new"
}
```
`title` is required. `status` values: `new`, `in_progress`, `validated`, `closed`.

**Response:** manual test object

### `PATCH /engagements/{program_id}/manual-tests/{test_id}`
Update a manual test. Only fields present in the body are changed.

**Response:** updated manual test object

### `DELETE /engagements/{program_id}/manual-tests/{test_id}`
Delete a manual test.

**Response**
```json
{ "message": "Manual test deleted" }
```

---

## Recon

### `GET /engagements/{program_id}/recon`
List recon items for a engagement, with optional filters. Items come from ffuf or httpx imports.

**Query parameters**
| Parameter | Default | Constraints | Description |
|---|---|---|---|
| `limit` | 100 | 1–500 | Max items to return |
| `offset` | 0 | ≥0 | Number of items to skip |
| `search` | (none) | — | Full-text filter across URL, host, path, title |
| `status_code` | (none) | — | Filter by HTTP status code (e.g. `200`) |
| `job_id` | (none) | — | Only items produced by this scan job (provenance link) |

**Response**
```json
{
  "recon": [
    {
      "id": "<uuid>",
      "source": "httpx",
      "url": "https://app.acme.com",
      "host": "app.acme.com",
      "title": "Acme App",
      "status_code": 200,
      "webserver": "nginx",
      "tech": ["React", "Node.js"],
      "content_type": "text/html",
      "length": 4321,
      "job_id": "<uuid | null>"
    }
  ],
  "total": 120,
  "offset": 0,
  "limit": 100
}
```

### `DELETE /engagements/{program_id}/recon`
Delete all recon items for a engagement. This is a bulk clear operation.

**Response**
```json
{ "message": "Recon items cleared" }
```

---

## Scans

### `GET /engagements/{program_id}/scans`
List scan items with pagination and optional status filter. Items come from nuclei imports.

**Query parameters**
| Parameter | Default | Constraints | Description |
|---|---|---|---|
| `limit` | 100 | 1–500 | Max items to return |
| `offset` | 0 | ≥0 | Number of items to skip |
| `status` | (none) | — | Filter by status value |
| `job_id` | (none) | — | Only items produced by this scan job (provenance link) |

**Response**
```json
{
  "scans": [
    {
      "id": "<uuid>",
      "source": "nuclei",
      "template_id": "CVE-2021-41773",
      "title": "Apache Path Traversal",
      "severity": "critical",
      "asset": "app.acme.com",
      "matched_at": "https://app.acme.com/cgi-bin/.%2e/.%2e/etc/passwd",
      "type": "http",
      "description": "...",
      "status": "new",
      "cwe": "CWE-22",
      "cvss": "9.8",
      "job_id": "<uuid | null>"
    }
  ],
  "total": 55,
  "offset": 0,
  "limit": 100
}
```
`job_id` is the scan job that produced the item (null for manual file imports), enabling a job → its-results provenance link.

### `POST /engagements/{program_id}/scans/triage`
AI triage over **raw** scan items (before promotion to findings). Sends a batch to Claude and returns a prioritized, false-positive-flagged list — turning the nuclei firehose into a ranked queue. Requires `ANTHROPIC_API_KEY` on the server.

**Request body**
```json
{ "ids": ["<uuid>", "<uuid>"] }
```
`ids` — specific scan items to triage. If empty, the newest `new`-status items are triaged (capped at 25 per call).

**Response**
```json
{
  "triage": [
    { "id": "<uuid>", "priority": "high", "false_positive": false, "rationale": "Confirmed SQLi on login." }
  ]
}
```
`priority` is one of `high`, `medium`, `low`, `noise`. Only ids that were part of the request are echoed back.

**Errors**
- `404` — engagement not found / not owned
- `503` — `ANTHROPIC_API_KEY` not configured
- `502` — model returned non-JSON or the request failed

### `PATCH /engagements/{program_id}/scans/{scan_id}`
Update the status of a single scan item.

**Request body**
```json
{ "status": "reviewed" }
```
`status` values: `new`, `reviewed`, `false_positive`, `promoted`.

**Response:** updated scan item object

### `POST /engagements/{program_id}/scans/bulk-status`
Update the status of multiple scan items at once.

**Request body**
```json
{ "ids": ["<uuid>", "<uuid>"], "status": "ignored" }
```

**Response**
```json
{ "updated": 2 }
```

---

## Imports

### `POST /engagements/{program_id}/imports`
Upload tool output for parsing and storage. Accepts `multipart/form-data`.

**Form fields**
| Field | Type | Description |
|---|---|---|
| `tool_type` | string | `ffuf`, `httpx`, or `nuclei` |
| `file` | file | `.json` or `.jsonl` output file |
| `job_id` | string (optional) | Scan job that produced this output; stamped onto every new recon/scan item for provenance. VardrRunner passes the id of the job it is executing. |

**File constraints**
- Extension: `.json` or `.jsonl`
- Content-Type: `application/json`, `application/x-ndjson`, `application/octet-stream`, or `text/plain`
- Max size: 2 MB (configurable via `MAX_UPLOAD_BYTES`)

**Response**
```json
{
  "message": "Import complete",
  "import_record": {
    "id": "<uuid>",
    "tool_type": "nuclei",
    "filename": "redacted",
    "imported_count": 42
  },
  "engagement": <full engagement object with updated counts>
}
```

**Errors**
- `400` — unsupported extension or content-type
- `413` — file exceeds size limit
- `422` — file content is not valid JSON or JSONL

---

## Scan Jobs

Scan jobs are created by the UI and executed by VardrRunner on the user's machine. Status flow: `pending → running → done | failed`.

A job object looks like:
```json
{
  "id": "<uuid>",
  "program_id": "<uuid>",
  "tool_type": "httpx",
  "target_source": "scope",
  "config": { "limit": 100 },
  "status": "pending",
  "depends_on": null,
  "created_at": "2026-06-09T10:00:00",
  "started_at": null,
  "completed_at": null,
  "error_message": ""
}
```
`depends_on` is the id of a job this stage waits on (null = no dependency). Set by `POST /engagements/{id}/pipelines`.

### `POST /engagements/{program_id}/jobs`
Queue a new scan job.

**Request body**
```json
{
  "tool_type": "httpx",
  "target_source": "scope",
  "config": { "status_code": 200, "limit": 500 },
  "depends_on": null
}
```
- `tool_type`: `"httpx"`, `"nuclei"`, `"subfinder"`, or `"nmap"`
- `target_source`: `"scope"` or `"recon"`
- `config` (optional): tool-specific options — `status_code`, `limit` for httpx; `severity`, `templates` for nuclei; `top_ports`, `timing` for nmap. Unknown keys are rejected.
- `depends_on` (optional): id of another job (same engagement, same owner) that must reach `done` before this job becomes eligible in `GET /jobs/pending`.

**Response:** job object with `status: "pending"`.

**Errors**
- `400` — invalid `tool_type`, invalid `target_source`, unknown config key, or `depends_on` referencing a job not in this engagement
- `404` — engagement not found or belongs to another user

### `POST /engagements/{program_id}/pipelines`
Queue an ordered chain of jobs where each stage waits on the previous one. The canonical recon pipeline `subfinder → httpx → nuclei` is one request. Validation is per-stage and identical to single-job creation, so a bad stage rejects the whole pipeline atomically (no partial writes).

**Request body**
```json
{
  "stages": [
    { "tool_type": "subfinder", "target_source": "scope" },
    { "tool_type": "httpx", "target_source": "recon" },
    { "tool_type": "nuclei", "target_source": "recon", "config": { "severity": "high,critical" } }
  ]
}
```
`stages` — 1 to 8 stages. Each stage has the same fields as a single job (minus `depends_on`, which is wired automatically).

**Response** — `201`
```json
{ "jobs": [ <job_object>, ... ] }
```
Jobs are returned in stage order; the first has `depends_on: null`, each subsequent one depends on the prior job's id.

### `POST /engagements/{program_id}/jobs/preview`
Dry-run: resolve the target list a job would run against **without queuing anything**. Lets the Composer confirm intent before launching ("about to scan 4,000 hosts?").

**Request body** — same shape as `POST .../jobs` (`tool_type`, `target_source`, optional `config`).

**Response**
```json
{
  "tool_type": "nuclei",
  "target_source": "recon",
  "count": 1284,
  "sample": ["https://a.example.com", "https://b.example.com"],
  "truncated": true
}
```
`count` is the total resolved targets; `sample` is the first 20; `truncated` is true when more exist. This mirrors what VardrRunner fetches (in-scope items for `scope`; recon rows for `recon`) and is an estimate — the runner applies final host normalization.

### `GET /engagements/{program_id}/jobs/stream`
Server-Sent Events (SSE) stream for real-time job status changes. The frontend opens this alongside polling; when a `job_update` event arrives, it triggers an immediate `GET /engagements/{id}/jobs` refresh.

Auth uses the standard `Authorization: Bearer` header via a streaming `fetch` (EventSource doesn't support custom headers). The connection sends a keepalive comment every 20 seconds.

**Response** — `text/event-stream`

On connect:
```
data: {"connected": true}
```

On job create or `done`/`failed` event:
```
data: {"type": "job_update", "job_id": "<uuid>", "status": "pending"}
```

Keepalive (every 20 s when idle):
```
: keepalive
```

**Errors**
- `401` — not authenticated
- `404` — engagement not found or belongs to another user

### `GET /engagements/{program_id}/jobs`
List all jobs for a engagement, newest first.

**Response**
```json
{ "jobs": [ <job_object>, ... ] }
```

### `GET /jobs/pending`
Return `pending` jobs owned by the authenticated user that are eligible to run now, oldest first. Used by VardrRunner to poll for work. Also materializes any due scheduled scans into pending jobs.

Pipeline stages with an unmet dependency are held back: a job with `depends_on` set is only returned once its parent reaches `done`. If the parent `failed` (or no longer exists), the dependent job is auto-failed with an `"upstream pipeline stage failed"` message so it never hangs the queue.

**Response**
```json
{ "jobs": [ <job_object>, ... ] }
```

### `POST /jobs/{job_id}/claim`
Atomically claim a pending job. Sets `status: "running"` and stamps `started_at` only if the job is currently `pending`. Returns `409` if the job is already running, done, or failed — prevents two VardrRunner instances from double-claiming the same job.

**Response:** updated job object with `status: "running"`.

**Errors**
- `401` — not authenticated
- `404` — job not found or belongs to another user
- `409` — job is not in `pending` state

### `PATCH /jobs/{job_id}`
Update a job's status. Used by VardrRunner to complete (`done`/`failed`) jobs after claiming via `POST /jobs/{id}/claim`.

**Request body**
```json
{
  "status": "done",
  "error_message": ""
}
```
- `status`: `"pending"`, `"running"`, `"done"`, or `"failed"`
- `error_message` (optional): set when marking `failed`
- Setting `status: "running"` stamps `started_at`; setting `"done"` or `"failed"` stamps `completed_at`

**Response:** updated job object.

**Errors**
- `400` — invalid status value
- `404` — job not found or belongs to another user

---

## Runner Heartbeat

VardrRunner reports its status to VardrMap so the Bridge UI can show real connectivity, hostname, version, and tool availability.

### `POST /runner/heartbeat`
VardrRunner posts its status here. Upserts one row per `(user, hostname)` pair — a laptop and a VPS report independently.

**Rate limit:** 60/minute (separate from the global 200/min default).

**Request body**
```json
{
  "hostname": "dev-laptop",
  "version":  "0.1.0",
  "os":       "Linux 6.5",
  "tools": {
    "httpx":     { "ok": true,  "version": "v1.6.9" },
    "nuclei":    { "ok": true,  "version": "v3.2.0" },
    "subfinder": { "ok": false, "version": null }
  }
}
```

**Response**
```json
{ "ok": true, "last_seen": "2026-06-10T12:34:56.789012" }
```

### `GET /runner/status`
Frontend polls this to check connectivity and display runner details in the Bridge. Returns `online: true` if a heartbeat was received within the last 5 minutes.

**Response (runner online)**
```json
{
  "online":    true,
  "last_seen": "2026-06-10T12:34:56.789012",
  "hostname":  "dev-laptop",
  "version":   "0.1.0",
  "os":        "Linux 6.5",
  "tools": {
    "httpx":     { "ok": true,  "version": "v1.6.9" },
    "nuclei":    { "ok": true,  "version": "v3.2.0" },
    "subfinder": { "ok": false, "version": null }
  }
}
```

**Response (no heartbeat ever sent)**
```json
{ "online": false, "last_seen": null, "hostname": null, "version": null, "os": null, "tools": {} }
```

---

## Job Events

VardrRunner posts lifecycle events as it executes a job. The frontend Terminal polls these to display real-time progress without an SSE connection.

### `POST /jobs/{job_id}/events`
VardrRunner posts a lifecycle event for a job it owns.

**Rate limit:** 600/minute (higher than the global 200/min default to accommodate frequent log events during fast jobs).

**Path params**
- `job_id` — UUID of the scan job

**Request body**
```json
{ "kind": "started", "text": "runner claimed job · 4 targets from scope" }
```

**Event kinds**

| `kind` | When posted |
|---|---|
| `started` | Runner claims the job and begins execution |
| `targets_resolved` | Target list has been built (text: count and source) |
| `running` | Tool subprocess has been launched (text: tool + target count) |
| `uploaded` | Results uploaded successfully (text: count of imported items) |
| `done` | Job completed successfully |
| `failed` | Job failed (text: error message) |
| `log` | Generic log line (reserved for future use) |

**Response** `201`
```json
{
  "id":         "uuid",
  "job_id":     "uuid",
  "kind":       "started",
  "text":       "runner claimed job · 4 targets from scope",
  "created_at": "2026-06-10T12:34:56.789012"
}
```

**Errors**
- `401` — not authenticated
- `404` — job not found or belongs to another user

### `GET /jobs/{job_id}/events`
Frontend polls this to stream job lifecycle events into the Terminal. Returns all events in chronological order.

**Path params**
- `job_id` — UUID of the scan job

**Response**
```json
{
  "events": [
    { "id": "uuid", "job_id": "uuid", "kind": "started",          "text": "runner claimed job · 4 targets from scope", "created_at": "…" },
    { "id": "uuid", "job_id": "uuid", "kind": "targets_resolved", "text": "4 targets from scope",                     "created_at": "…" },
    { "id": "uuid", "job_id": "uuid", "kind": "running",          "text": "running httpx against 4 target(s)",        "created_at": "…" },
    { "id": "uuid", "job_id": "uuid", "kind": "uploaded",         "text": "imported 12 result(s)",                    "created_at": "…" },
    { "id": "uuid", "job_id": "uuid", "kind": "done",             "text": "",                                         "created_at": "…" }
  ]
}
```

**Errors**
- `401` — not authenticated
- `404` — job not found or belongs to another user

---

## Services

Open ports and services discovered by nmap. All endpoints are BOLA-scoped: the engagement must belong to the authenticated user.

**Scope requirements:** `POST /services` accepts runner-scoped API keys (VardrRunner posts nmap results here). `GET` and `DELETE` require a full-scope key or browser JWT.

A service object looks like:
```json
{
  "id": "<uuid>",
  "program_id": "<uuid>",
  "host": "app.acme.com",
  "port": 443,
  "protocol": "tcp",
  "service_name": "https",
  "product": "nginx",
  "version": "1.24.0",
  "state": "open",
  "source": "nmap",
  "created_at": "2026-06-11T10:00:00",
  "last_scanned_at": "2026-06-11T12:30:00"
}
```

### `GET /engagements/{program_id}/services`
List all services for a engagement, ordered by host then port.

**Response**
```json
{ "services": [ <service_object>, ... ], "total": 42 }
```

### `POST /engagements/{program_id}/services`
Bulk-upsert services. VardrRunner posts nmap results here after a scan job completes. Upserts on `(host, port, protocol)` — updates metadata if the combination already exists.

**Request body**
```json
{
  "services": [
    { "host": "app.acme.com", "port": 443, "protocol": "tcp", "service_name": "https", "product": "nginx", "version": "1.24.0" }
  ]
}
```

**Field constraints**
| Field | Constraint |
|---|---|
| `host` | 1–500 chars, required |
| `port` | 1–65535, required |
| `protocol` | `"tcp"` or `"udp"`, default `"tcp"` |
| `service_name` | max 100 chars, default `""` |
| `product` | max 200 chars, default `""` |
| `version` | max 100 chars, default `""` |
| `state` | max 20 chars, default `"open"` |
| `source` | max 50 chars, default `"nmap"` |

Maximum 5 000 services per request.

**Response** `201`
```json
{ "created": 3, "updated": 1 }
```

### `DELETE /engagements/{program_id}/services/{service_id}`
Delete a single service record.

**Response**
```json
{ "message": "Service deleted" }
```

**Errors**
- `401` — not authenticated
- `404` — engagement or service not found, or belongs to another user
- `422` — invalid field value (e.g. port out of range)

**`last_scanned_at`** — stamped on both create and upsert (whenever VardrRunner reports the port). Reflects when the service was last seen by nmap. `created_at` is only set once at insert time.

---

## Target Radar

Program discovery feed — fetches public bug bounty program listings from Bugcrowd and HackerOne and surfaces newly seen programs. All endpoints are BOLA-scoped by authenticated user.

A radar program object looks like:
```json
{
  "id": "<uuid>",
  "platform": "bugcrowd",
  "platform_id": "prog-alpha",
  "name": "Alpha Program",
  "url": "https://bugcrowd.com/prog-alpha",
  "max_payout": 5000,
  "is_new": true,
  "discovered_at": "2026-06-11T10:00:00",
  "last_fetched_at": "2026-06-11T10:00:00"
}
```

### `GET /radar`
Return stored radar programs for the authenticated user, ordered by `discovered_at` descending. Marks all returned programs as seen (`is_new = false`).

**Query parameters**
| Parameter | Description |
|---|---|
| `platform` | Optional filter: `bugcrowd` or `hackerone` |

**Response**
```json
{ "programs": [ <radar_object>, ... ], "total": 42, "new_count": 3 }
```

`new_count` reflects how many programs were `is_new = true` before this call marked them as seen.

### `POST /radar/refresh`
Fetch program listings from platform APIs and upsert into the database. Programs that have never been seen before are inserted with `is_new = true`. Programs already stored are updated in place (`last_fetched_at` refreshed, metadata synced).

**Query parameters**
| Parameter | Description |
|---|---|
| `platform` | Optional: `bugcrowd` or `hackerone`. Omit to refresh all platforms. |

**Response**
```json
{ "new": 12, "updated": 38, "platforms": ["bugcrowd", "hackerone"] }
```

**Errors**
- `400` — unknown platform name
- `502` — upstream platform API request failed


## Scan Jobs (updated)

### `DELETE /jobs/{job_id}`
Permanently delete a job and all its events. Intended for removing stuck jobs that a crashed runner left in `running` state. Any job status is accepted.

**Errors**
- `404` — job not found or belongs to another user

---

## Scheduled Scans

Recurring scan definitions. There is no backend cron: due schedules are materialized into pending `scan_jobs` whenever VardrRunner polls `GET /jobs/pending`, so schedules only fire while a runner is connected. New schedules are due immediately — the first job is created on the runner's next poll. After a runner outage, one catch-up job is created (not one per missed interval).

**Schedule object shape**
```json
{
  "id":            "uuid",
  "program_id":    "uuid",
  "tool_type":     "httpx",
  "target_source": "scope",
  "config":        { "limit": 50 },
  "interval":      "daily",
  "enabled":       true,
  "last_run_at":   "2026-06-12T10:00:00+00:00",
  "next_run_at":   "2026-06-13T10:00:00+00:00",
  "created_at":    "2026-06-12T10:00:00+00:00"
}
```

### `GET /engagements/{program_id}/schedules`
List all schedules for a engagement, newest first.

**Response**
```json
{ "schedules": [ <schedule_object>, ... ], "total": 2 }
```

### `POST /engagements/{program_id}/schedules`
Create a recurring scan.

**Request body**
| Field | Type | Required | Description |
|---|---|---|---|
| `tool_type` | string | yes | `httpx`, `nuclei`, `subfinder`, or `nmap` |
| `target_source` | string | yes | `scope` or `recon` |
| `config` | object | no | Tool config, same validation as job creation |
| `interval` | string | yes | `hourly`, `daily`, or `weekly` |

**Errors**
- `400` — invalid tool, source, interval, or config keys
- `404` — engagement not found or belongs to another user

### `PATCH /engagements/{program_id}/schedules/{schedule_id}`
Update `enabled` (pause/resume) and/or `interval`.

### `DELETE /engagements/{program_id}/schedules/{schedule_id}`
Permanently delete a schedule. Jobs already materialized from it are unaffected.

---

## Scan Profiles

Reusable saved tool + config presets for a engagement. A hunter can save a frequently-used scan (e.g. "nuclei CVE sweep") and queue it in one click instead of retyping config. Config is validated identically to job creation, so a profile can never store a scan the job endpoint would reject.

**Profile object shape**
```json
{
  "id":            "uuid",
  "program_id":    "uuid",
  "name":          "CVE sweep",
  "tool_type":     "nuclei",
  "target_source": "recon",
  "config":        { "severity": "high,critical", "templates": "cves" },
  "created_at":    "2026-07-22T10:00:00+00:00"
}
```

### `GET /engagements/{program_id}/scan-profiles`
List all scan profiles for a engagement, newest first.

**Response**
```json
{ "profiles": [ <profile_object>, ... ] }
```

### `POST /engagements/{program_id}/scan-profiles`
Create a saved profile. `201` on success.

**Request body**
| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | 1–100 chars |
| `tool_type` | string | yes | `httpx`, `nuclei`, `subfinder`, or `nmap` |
| `target_source` | string | yes | `scope` or `recon` |
| `config` | object | no | Tool config, same validation as job creation |

**Errors**
- `400` — invalid tool, source, or config keys
- `403` — viewer-role member (read-only)
- `404` — engagement not found or belongs to another user

### `DELETE /engagements/{program_id}/scan-profiles/{profile_id}`
Permanently delete a profile.

---

## Settings

Per-user notification settings.

### `GET /settings`
Returns the authenticated user's settings (defaults if never saved).

**Response**
```json
{ "webhook_url": "https://discord.com/api/webhooks/...", "notify_min_severity": "high" }
```

### `PATCH /settings`
Update settings. `webhook_url` must be an HTTPS URL and may not point at localhost or a private/link-local address (SSRF guard); send `""` to disable notifications. `notify_min_severity` must be `info`/`low`/`medium`/`high`/`critical`.

Notifications fire (as a Discord/Slack-compatible webhook POST) when:
- a scan job is marked `failed` (except operator cancels), or
- a nuclei import contains findings at or above `notify_min_severity`.

**Errors**
- `400` — non-HTTPS or private-address webhook URL, or invalid severity

---

## Engagement Members

Invite GitHub collaborators to access a engagement. Only the engagement owner can manage membership and delete the engagement.

**Roles**

| Role | Read | Write (findings, reports, scope) | Manage members | Delete engagement |
|---|---|---|---|---|
| `owner` | yes | yes | yes | yes |
| `member` | yes | yes | no | no |
| `viewer` | yes | no | no | no |

`viewer` members receive `403` on all mutation routes (POST/DELETE for findings, reports, scope items). All roles can read.

### `GET /engagements/{program_id}/members`
List invited members. Accessible by owner or any member.

**Response**
```json
{
  "owner_github_id": "gh_owner_id",
  "members": [
    { "id": "<uuid>", "program_id": "<uuid>", "member_github_id": "gh_collaborator", "role": "member", "invited_at": "2026-06-12T10:00:00" }
  ]
}
```

### `POST /engagements/{program_id}/members`
Invite a collaborator by GitHub ID. Owner only. Max 20 members per engagement.

**Request body**
```json
{ "github_id": "gh_collaborator", "role": "member" }
```
`role` is optional — defaults to `"member"`. Accepted values: `"member"`, `"viewer"`.

**Errors**
- `400` — invited user is the owner, or max members reached
- `403` — caller is not the engagement owner
- `409` — user already a member

### `DELETE /engagements/{program_id}/members/{member_github_id}`
Remove a collaborator. Owner only.

**Errors**
- `403` — caller is not the engagement owner
- `404` — member not found

---

## Imports (updated)

### `POST /engagements/{program_id}/imports`
The response now includes `new_count` for httpx and ffuf imports — the number of recon items that were not previously seen for this engagement. Re-importing the same file a second time will produce `imported_count: 0, new_count: 0`. A new `first_seen_at` timestamp is set on each unique recon item at discovery time and never overwritten. A webhook fires (if configured) when `new_count > 0` for httpx imports.

Updated response shape:
```json
{
  "message":        "Import complete",
  "imported_count": 12,
  "new_count":       8,
  "import_record":  { ... },
  "engagement":        { ... }
}
```

---

## Runner Status (updated)

### `GET /runner/status`
Now returns a `runners` array — one entry per machine that has sent a heartbeat (newest first), each with `online`, `last_seen`, `hostname`, `version`, `os`, and `tools`. Heartbeats are upserted per `(user, hostname)` so a laptop and a VPS report independently. Top-level fields mirror the most recently seen runner for backward compatibility; top-level `online` is true if **any** runner is online.

---

## Clients

An organisation engagements are performed for. Optional: bug bounty work has no
client, because the programme itself is the counterparty.

Clients are scoped to the user who created them and are **not** shared through
engagement membership — a collaborator invited to one engagement should not see the
other engagements a client record covers. Another user's client returns `404`.

### `GET /clients`
List the calling user's clients, ordered by name.

**Response:** array of client objects

### `POST /clients`
Create a client.

**Request body**
```json
{ "name": "Acme Corp", "contact_name": "Dana Lee", "contact_email": "dana@acme.com", "notes": "" }
```
Only `name` is required.

**Response:** `201` client object

### `GET /clients/{client_id}`
Fetch one client.

**Response:** client object, or `404`

### `PATCH /clients/{client_id}`
Update any subset of `name`, `contact_name`, `contact_email`, `notes`.

**Response:** client object

### `DELETE /clients/{client_id}`
Delete a client. Its engagements are **detached, not deleted** — `client_id` is
set to null on each — because the testing record outlives the commercial
relationship.

**Response:** `204`, no body

---

---

## Authorizations

The record of permission to test a engagement, and the window it covers. This is
the artifact that separates a professional engagement from bounty hunting: a
named person authorised named activity, between two dates.

Access is scoped through the engagement, so owners and invited members can read the
authorisation covering work they are doing. Viewers cannot create or edit one.

Authorisations are **append-mostly**. To supersede one, mark it `expired` and
create a new row rather than editing it — the value of the record is being able
to say later what was permitted at the time.

All datetimes are ISO-8601 strings; a trailing `Z` is accepted.

### `GET /engagements/{program_id}/authorizations`
List a engagement's authorisations, newest first.

**Response:** array of authorization objects

### `POST /engagements/{program_id}/authorizations`
Record an authorisation.

**Request body**
```json
{
  "permits": "Unauthenticated and authenticated testing of the web application and its API.",
  "authorized_by": "Dana Lee, CTO",
  "authorized_at": "2026-08-01T09:00:00Z",
  "reference": "SOW-2026-014",
  "window_start": "2026-08-04T00:00:00Z",
  "window_end": "2026-08-18T23:59:59Z",
  "notes": ""
}
```
Every field is optional. A missing `window_start` or `window_end` means open on
that side — normal for a bounty programme, unusual for an engagement.

**Response:** `201` authorization object. Created with `status: "active"`.

### `PATCH /engagements/{program_id}/authorizations/{authorization_id}`
Update an authorisation, most often to set `status` to `expired` or `revoked`.

`status` values: `active`, `expired`, `revoked`.

Fields are updated only when present in the request body. For the three date
fields (`authorized_at`, `window_start`, `window_end`), sending `null`
explicitly clears that date (e.g. to make a fixed-window authorisation
open-ended); omitting the field leaves it unchanged.

**Response:** authorization object

### `GET /engagements/{program_id}/authorization/active`
The authorisation currently permitting work, or `null`.

An authorisation qualifies when its `status` is `active` and the present moment
falls inside its window. This is the question the rest of the toolchain needs
answered before it runs anything.

**Response:** authorization object, or `null`

---

---

## Deprecated: `/programs/*`

The resource was renamed from *program* to *engagement* when VardrMap widened
from bug bounty work to professional testing. Every `/engagements/*` route is
still reachable at the old `/programs/*` path, which is rewritten before
routing, so existing VardrRunner installs and any scripts using a `vmap_` key
keep working unchanged.

The alias is transitional. Move to `/engagements/*`; `/programs/*` will be
removed once VardrRunner and the frontend are both updated.

Note that *program* still has a distinct, correct meaning elsewhere in this API:
a **bug bounty program** on HackerOne or Bugcrowd, as surfaced by
`GET /radar`. Those are not engagements and were not renamed.
