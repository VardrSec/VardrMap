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
    { "id": "<uuid>", "label": "Burp Suite", "created_at": "2026-06-08T10:00:00", "last_used_at": "2026-06-11T09:00:00" }
  ]
}
```

### `POST /auth/apikeys`
Generate a new API key. The plaintext token is returned **once** in this response and is not stored. Maximum 10 keys per user.

**Request body**
```json
{ "label": "Burp Suite" }
```
`label` is optional (max 100 chars). Validated and sanitized server-side.

**Response**
```json
{
  "id": "<uuid>",
  "label": "Burp Suite",
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

## Programs

### `GET /programs`
List all programs belonging to the current user. Each program includes aggregate stats — not full arrays of findings, reports, or manual tests.

**Response**
```json
{
  "programs": [ <program_object>, ... ]
}
```

### `POST /programs`
Create a new program.

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

**Response:** full program object

### `GET /programs/{program_id}`
Get a single program by ID. Returns 404 if it does not belong to the current user.

**Response:** full program object

### `PATCH /programs/{program_id}`
Update program fields. Only fields included in the request body are changed.

**Request body:** any subset of `POST /programs` fields

**Response:** updated program object

### `DELETE /programs/{program_id}`
Delete a program. Cascades to all child records (scope, findings, reports, manual tests, recon, scans, imports).

**Response**
```json
{ "message": "Program deleted" }
```

**Program object shape**
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
  "reports_count": 3
}
```

---

## Scope

### `POST /programs/{program_id}/scope/in`
Add an in-scope item.

**Request body**
```json
{ "value": "*.acme.com", "kind": "domain", "notes": "" }
```
`kind` values: `domain`, `subdomain`, `url`, `cidr`, `api`, `mobile`. `notes` is optional.

**Response:** scope item object

### `POST /programs/{program_id}/scope/out`
Add an out-of-scope item. Same request body as above.

**Response:** scope item object

### `DELETE /programs/{program_id}/scope/{scope_type}/{item_id}`
Remove a scope item. `scope_type` must be `in` or `out`.

**Response**
```json
{ "message": "Scope item deleted" }
```

---

## Findings

### `GET /programs/{program_id}/findings`
List findings for a program, ordered by `created_at` descending.

**Query parameters**
| Parameter | Default | Constraints | Description |
|---|---|---|---|
| `limit` | 50 | 1–200 | Max items to return |
| `offset` | 0 | ≥0 | Number of items to skip |

**Response**
```json
{
  "findings": [ { "id": "<uuid>", "title": "...", "severity": "high", "asset": "app.acme.com", "status": "triaged", "summary": "...", "steps": "...", "impact": "...", "remediation": "...", "created_at": "2026-06-05T09:00:00" } ],
  "total": 42,
  "offset": 0,
  "limit": 50
}
```

### `POST /programs/{program_id}/findings`
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

### `PATCH /programs/{program_id}/findings/{finding_id}`
Update a finding. Only fields present in the body are changed.

**Response:** updated finding object

### `DELETE /programs/{program_id}/findings/{finding_id}`
Delete a finding.

**Response**
```json
{ "message": "Finding deleted" }
```

### `POST /programs/{program_id}/findings/{finding_id}/suggest`
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

### `GET /programs/{program_id}/reports`
List reports for a program, ordered by `created_at` descending.

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

### `POST /programs/{program_id}/reports`
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

### `PATCH /programs/{program_id}/reports/{report_id}`
Update a report. Only fields present in the body are changed.

**Response:** updated report object

### `DELETE /programs/{program_id}/reports/{report_id}`
Delete a report.

**Response**
```json
{ "message": "Report deleted" }
```

---

## Manual Tests

### `GET /programs/{program_id}/manual-tests`
List all manual test cases for a program, ordered by `created_at` descending.

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
      "status": "confirmed"
    }
  ]
}
```

### `POST /programs/{program_id}/manual-tests`
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
`title` is required. `status` values: `new`, `in-progress`, `confirmed`, `not-exploitable`.

**Response:** manual test object

### `PATCH /programs/{program_id}/manual-tests/{test_id}`
Update a manual test. Only fields present in the body are changed.

**Response:** updated manual test object

### `DELETE /programs/{program_id}/manual-tests/{test_id}`
Delete a manual test.

**Response**
```json
{ "message": "Manual test deleted" }
```

---

## Recon

### `GET /programs/{program_id}/recon`
List recon items for a program, with optional filters. Items come from ffuf or httpx imports.

**Query parameters**
| Parameter | Default | Constraints | Description |
|---|---|---|---|
| `limit` | 100 | 1–500 | Max items to return |
| `offset` | 0 | ≥0 | Number of items to skip |
| `search` | (none) | — | Full-text filter across URL, host, path, title |
| `status_code` | (none) | — | Filter by HTTP status code (e.g. `200`) |

**Response**
```json
{
  "recon_items": [
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
      "length": 4321
    }
  ]
}
```

### `DELETE /programs/{program_id}/recon`
Delete all recon items for a program. This is a bulk clear operation.

**Response**
```json
{ "message": "Recon items cleared" }
```

---

## Scans

### `GET /programs/{program_id}/scans`
List scan items with pagination and optional status filter. Items come from nuclei imports.

**Query parameters**
| Parameter | Default | Constraints | Description |
|---|---|---|---|
| `limit` | 100 | 1–500 | Max items to return |
| `offset` | 0 | ≥0 | Number of items to skip |
| `status` | (none) | — | Filter by status value |

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
      "cvss": "9.8"
    }
  ],
  "total": 55,
  "offset": 0,
  "limit": 100
}
```

### `PATCH /programs/{program_id}/scans/{scan_id}`
Update the status of a single scan item.

**Request body**
```json
{ "status": "triaged" }
```
`status` values: `new`, `triaged`, `accepted`, `rejected`, `ignored`.

**Response:** updated scan item object

### `POST /programs/{program_id}/scans/bulk-status`
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

### `POST /programs/{program_id}/imports`
Upload tool output for parsing and storage. Accepts `multipart/form-data`.

**Form fields**
| Field | Type | Description |
|---|---|---|
| `tool_type` | string | `ffuf`, `httpx`, or `nuclei` |
| `file` | file | `.json` or `.jsonl` output file |

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
  "program": <full program object with updated counts>
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
  "created_at": "2026-06-09T10:00:00",
  "started_at": null,
  "completed_at": null,
  "error_message": ""
}
```

### `POST /programs/{program_id}/jobs`
Queue a new scan job.

**Request body**
```json
{
  "tool_type": "httpx",
  "target_source": "scope",
  "config": { "status_code": 200, "limit": 500 }
}
```
- `tool_type`: `"httpx"`, `"nuclei"`, `"subfinder"`, or `"nmap"`
- `target_source`: `"scope"` or `"recon"`
- `config` (optional): tool-specific options — `status_code`, `limit` for httpx; `severity`, `templates` for nuclei; `top_ports`, `timing` for nmap. Unknown keys are rejected.

**Response:** job object with `status: "pending"`.

**Errors**
- `400` — invalid `tool_type`, invalid `target_source`, or unknown config key for the tool
- `404` — program not found or belongs to another user

### `GET /programs/{program_id}/jobs`
List all jobs for a program, newest first.

**Response**
```json
{ "jobs": [ <job_object>, ... ] }
```

### `GET /jobs/pending`
Return all `pending` jobs owned by the authenticated user, oldest first. Used by VardrRunner to poll for work.

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
VardrRunner posts its status here. Upserts one row per authenticated user (one row per user — not per device).

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

Open ports and services discovered by nmap. All endpoints are BOLA-scoped: the program must belong to the authenticated user.

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

### `GET /programs/{program_id}/services`
List all services for a program, ordered by host then port.

**Response**
```json
{ "services": [ <service_object>, ... ], "total": 42 }
```

### `POST /programs/{program_id}/services`
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

### `DELETE /programs/{program_id}/services/{service_id}`
Delete a single service record.

**Response**
```json
{ "message": "Service deleted" }
```

**Errors**
- `401` — not authenticated
- `404` — program or service not found, or belongs to another user
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


## Submissions

Tracks the full lifecycle of a bug bounty submission from filed to resolved. Statuses: `submitted` → `triaged` → `accepted` | `duplicate` | `na` | `paid` | `rejected`.

**Submission object shape**
```json
{
  "id":                 "uuid",
  "program_id":         "uuid",
  "finding_id":         "uuid or empty string",
  "report_id":          "uuid or empty string",
  "platform":           "HackerOne",
  "platform_reference": "report-12345",
  "title":              "XSS in search parameter",
  "status":             "submitted",
  "payout_usd":         500.0,
  "severity":           "high",
  "notes":              "Triaged within 2 hours.",
  "submitted_at":       "2026-06-12T10:00:00+00:00",
  "resolved_at":        null,
  "created_at":         "2026-06-12T10:00:00+00:00"
}
```

### `GET /programs/{program_id}/submissions`
List all submissions for a program, ordered newest-first.

**Response**
```json
{ "submissions": [ <submission_object>, ... ], "total": 5 }
```

### `POST /programs/{program_id}/submissions`
Log a new submission.

**Request body**
| Field | Type | Required | Description |
|---|---|---|---|
| `title` | string | yes | Short report title |
| `platform` | string | no | Platform name (e.g. `HackerOne`, `Bugcrowd`) |
| `platform_reference` | string | no | Report ID or URL on the platform |
| `finding_id` | string | no | Soft reference to a finding |
| `report_id` | string | no | Soft reference to a report |
| `severity` | string | no | `critical`, `high`, `medium`, `low`, or `info` |
| `status` | string | no | Initial status (default: `submitted`) |
| `payout_usd` | number | no | Payout amount in USD |
| `notes` | string | no | Free-form notes |

### `PATCH /programs/{program_id}/submissions/{submission_id}`
Update a submission. Partial update — only provided fields are changed. When `status` transitions to a terminal state (`accepted`, `duplicate`, `na`, `paid`, `rejected`) and `resolved_at` is not set, it is auto-stamped to the current UTC time.

**Errors**
- `404` — submission not found or belongs to another user
- `400` — malformed `resolved_at` datetime

### `DELETE /programs/{program_id}/submissions/{submission_id}`
Permanently delete a submission.

**Errors**
- `404` — submission not found or belongs to another user

---

## Scan Jobs (updated)

### `DELETE /jobs/{job_id}`
Permanently delete a job and all its events. Intended for removing stuck jobs that a crashed runner left in `running` state. Any job status is accepted.

**Errors**
- `404` — job not found or belongs to another user
