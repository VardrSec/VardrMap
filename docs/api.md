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
    { "id": "<uuid>", "label": "Burp Suite", "created_at": "2026-06-08T10:00:00" }
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
`kind` values: `domain`, `ip`, `url`, `cidr`, `mobile`, `other`. `notes` is optional.

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
`title` is required. `severity` values: `critical`, `high`, `medium`, `low`, `info`. `status` values: `new`, `triaged`, `accepted`, `rejected`, `informational`.

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
- `tool_type`: `"httpx"` or `"nuclei"`
- `target_source`: `"scope"` or `"recon"`
- `config` (optional): tool-specific options — `status_code`, `limit` for httpx; `severity`, `templates` for nuclei

**Response:** job object with `status: "pending"`.

**Errors**
- `400` — invalid `tool_type` or `target_source`
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

### `PATCH /jobs/{job_id}`
Update a job's status. Used by VardrRunner to claim (`running`) and complete (`done`/`failed`) jobs.

**Request body**
```json
{
  "status": "running",
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
