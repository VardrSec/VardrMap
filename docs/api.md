# API Reference

All endpoints require `Authorization: Bearer <token>` unless noted otherwise. The token is either a browser JWT (minted by the frontend after GitHub OAuth) or a personal API key with the `vmap_` prefix. See [architecture.md](architecture.md) for how each token type is resolved.

Responses are JSON unless a streaming endpoint is documented otherwise. Timestamps are ISO 8601 UTC strings.

**Base URL (production):** set by `NEXT_PUBLIC_API_URL` — the browser sends authenticated requests directly to this value; backend CORS must allow the frontend origin.

---

## Optional local authentication

`VARDRMAP_AUTH_METHODS` explicitly selects `github` (default), `local` or
`github,local`. Unknown/empty settings fail closed. `GET /auth/methods` is public
and returns the enabled method names. Existing bearer/API-key authorization is
retained; local users pass through the same ownership/org/role checks.

Local browser authentication requires HTTPS. Passwords and raw session secrets
are never returned in JSON. Responses are not cached; authentication validation
errors use a fixed message without echoing submitted passwords.

| Endpoint | Authentication and behavior |
|---|---|
| `POST /auth/local/login` | JSON `username`/`password`, allowed Origin, HTTPS. Generic 401 on invalid/locked credentials; 10 requests/minute per client IP. Sets a new secure HTTP-only session cookie. |
| `GET /auth/local/session` | Valid local cookie; returns `authMethod: local`, user metadata and session-bound `csrfToken`, never a bearer/session token. |
| `POST /auth/local/logout` | Local cookie, allowed Origin and `X-CSRF-Token`; revokes the server session and clears the cookie. |
| `POST /auth/local/password` | Same cookie/Origin/CSRF checks plus `current_password` and `new_password`; rotates the current session and revokes the user's other local browser sessions. Limited to 5 requests/minute per IP. |

Every cookie-authenticated API write, including existing engagement/key/report
routes, requires an allowed Origin and matching `X-CSRF-Token`. Bearer requests
retain their existing requirements and never fall back to a cookie when invalid.
Session cookies are host-only `Secure; HttpOnly; SameSite=Lax; Path=/` with an
eight-hour absolute limit and 30-minute server-enforced idle limit. Logout,
password change and terminal recovery revoke sessions immediately for subsequent
requests. API keys remain separate credentials with their existing revocation flow.

There is no anonymous HTTP bootstrap/registration endpoint. Initial local account
creation and recovery are explicit terminal operations documented in
[local authentication](local-authentication.md). The initial administrator is the
owner of its personal workspace, without a cross-tenant or global permission bypass.

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

### `GET /ready`

Value-free API/database readiness, separate from `/health` liveness. No auth is
required so diagnostics still work when the database needed by API-key auth is
unavailable. This does not grant access to any engagement or user data. Existing
authentication and authorization requirements are unchanged.

Returns **200** only when a database read succeeds and its Alembic revision marker
matches the single head shipped with this backend. Returns **503** otherwise.
Responses use `Cache-Control: no-store` and include the UTC observation time:

```json
{
  "schema_version": 1,
  "component": "vardrmap-api",
  "status": "ready",
  "checked_at": "2026-10-25T00:00:00+00:00",
  "checks": {"database": "ok", "migrations": "current"}
}
```

`database` is `ok` or `unavailable`. `migrations` is `current`, `not_current`,
`unavailable` (migration package/metadata cannot be read), or `not_checked` (the
database is unavailable). Missing, older, newer or multiple database revisions
are `not_current`; missing/multiple packaged heads are `unavailable`. Revision
identifiers, connection strings, credentials and exception text are never returned.

This endpoint reads state; it never stamps/upgrades a schema, creates user data,
installs tools or executes scans. It checks a revision marker, not every table or
the UI/runner/target workflow. A future distribution must test that complete path
separately. Consume this v1 contract explicitly; older Map versions return 404.

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
List all engagements accessible through ownership, organization membership or an engagement invitation. Each engagement includes aggregate stats — not full arrays of findings, reports, or manual tests.

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
Only `name` is required. All other fields default to empty string. `max_request_rate` (optional, 1–1000) is a per-engagement ceiling on scan-job request rate; when set, the job API caps a job's `rate` for the traffic-sending tools to it, and `null` means no ceiling.

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

### `POST /engagements/{program_id}/stop-work`
Engage the emergency brake. While engaged, **every** execution for this engagement is denied by the policy engine regardless of scope, testing window, or authorization status.

Idempotent — re-engaging an already-stopped engagement succeeds and leaves the original `stop_work_at` unchanged. During an incident an operator needs certainty that the brake is on, not an error about pulling it twice.

Any member with write access may engage a stop. Releasing it requires the engagement owner.

**Body**
| Field | Type | Required | Notes |
|---|---|---|---|
| `reason` | string | no | Max 500 chars, HTML stripped |

**Response** — the engagement object, with `stop_work_at` set.

### `DELETE /engagements/{program_id}/stop-work`
Release the emergency brake. **Owner only** — engaging a stop is a safety action anyone on the engagement should be able to take; lifting one is an authorization decision.

**Response** — the engagement object, with `stop_work_at` cleared.

**Errors**
- `403` — caller is a member but not the owner
- `404` — engagement not found or caller is not a member

### Scope warnings

Job creation, job claim, and the `PATCH /jobs/{id}` transition into `running` all run the policy evaluator (`backend/policy.py`). Findings are **advisory** — staying in scope is the operator's responsibility, so a job outside scope or outside its testing window is still queued and still runs. Each of those three responses carries a `warnings` array:

```json
{
  "id": "<uuid>",
  "status": "pending",
  "warnings": [
    {
      "reason": "outside_testing_window",
      "message": "The testing window has closed."
    }
  ]
}
```

The array is empty when nothing is flagged. `reason` is a stable code safe to branch on — a client that wants to treat a warning as fatal can. Current values: `engagement_not_active`, `authorization_missing`, `authorization_not_active`, `outside_testing_window`, `capability_prohibited`, `target_excluded`, `target_out_of_scope`, `scope_ambiguous`.

Warnings are returned to the caller and **not** recorded in `audit_logs`.

### Stop-work refusal (`403`)

`stop_work_active` is the one finding that still blocks. It is the operator's own emergency brake rather than a judgement about scope, so job creation, claim, and the transition into `running` all refuse while it is engaged:

```json
{
  "detail": {
    "error": "stop_work_active",
    "reason": "stop_work_active",
    "message": "Stop-work is engaged for this engagement."
  }
}
```

Transitions to `done` / `failed` are never blocked — a runner must always be able to report the outcome of work already performed. See `docs/security-model.md`.

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
  "findings_by_status":   { "new": 4, "candidate": 1, "triaged": 2, "in_progress": 1, "closed": 0 },
  "reports_count": 3,
  "services_count": 8,
  "my_role": "owner"
}
```

`my_role` is the calling user's role in this engagement: `"owner"` (the engagement owner), `"member"` (invited collaborator with write access), or `"viewer"` (invited collaborator with read-only access). Viewers receive `403` on mutation routes (POST/DELETE findings, reports, scope items).

---

## Evidence

Proof attached to a finding. **Redaction happens on write, never on render** — the `body` column stores already-redacted text.

Storing a raw `Authorization` header and stripping it in the serializer means one forgotten path (a log line, an export, a debug endpoint, an error message) leaks it. What is never stored cannot leak from a path nobody remembered.

Structure is preserved deliberately: `Authorization: Bearer [REDACTED]` still proves the request was authenticated, which is frequently the point of the evidence.

**What is redacted:** sensitive header values (`Authorization`, `Cookie`, `Set-Cookie`, `X-API-Key`, …), sensitive body/query keys (`password`, `token`, `client_secret`, `api_key`, …), credentials embedded in URLs, bare JWTs, and `Bearer`/`Basic` tokens in prose. Configurable extra keys are supported.

### `POST /engagements/{program_id}/evidence`

| Field | Type | Notes |
|---|---|---|
| `kind` | string | `http_request` \| `http_response` \| `terminal_output` \| `tool_result` \| `note` \| `screenshot` |
| `title` | string | max 200 |
| `body` | string | max 200,000 chars — bounded so a pasted response cannot exhaust the row |
| `finding_id` | string | optional; must belong to this engagement |
| `sensitivity` | string | `public` \| `internal` \| `confidential` \| `restricted` |
| `retention` | string | `engagement` \| `90d` \| `permanent` |

`content_hash` is SHA-256 over the **stored** (redacted) body — integrity of the artefact as retained, which is the only thing we can honestly attest to.

**Errors** — `400` invalid enum or foreign `finding_id`; `422` body too large; `404` engagement not accessible.

### `GET /engagements/{program_id}/evidence`
Filter with `finding_id`, `job_id`, `case_id` (stored case UUID), and/or `identity_id`
(case-sensitive). Filters combine and remain scoped to this engagement. Paginate
with `limit` (max 200) and `offset`. Each row includes nullable `job_id`, `case_id`,
`case_ref` (logical Gate case id), `identity_id`, `observed_outcome`, and
`expected_decision`. These are set by Gate upload, not accepted by manual evidence
creation. Historical/manual rows keep null provenance; it is never inferred. Overlong identity
ids (above 200 characters) retain their redacted text in the body and use null
identity metadata, never a truncated identifier that names a different identity.

### `DELETE /engagements/{program_id}/evidence/{evidence_id}`

---

## Attack Surface (Assets)

The asset graph. Before it existed, a host lived as five unrelated free-text columns with no join key, and "everything we know about this host" was a fuzzy `LIKE` across four tables.

Identity is `canonical_key` — a pure function of the observed string, unique per engagement. `api.acme.com`, `https://api.acme.com/`, and `api.acme.com:443` converge; two genuinely different hosts never do. Anything unclassifiable is left unlinked rather than forced into a bucket, because a wrong merge is unrecoverable.

### `GET /engagements/{program_id}/assets`
List assets. Query params: `asset_type`, `q` (hostname **prefix** — deliberately not a leading-wildcard LIKE, which would scan the table), `limit` (max 500), `offset`.

```json
{ "assets": [ { "id": "<uuid>", "canonical_key": "domain:api.acme.com:443", "asset_type": "domain",
                "label": "api.acme.com:443", "hostname": "api.acme.com", "ip": "", "port": 443,
                "environment": "", "criticality": "", "exposure": "", "confidence": "confirmed",
                "source": "httpx", "first_seen_at": "...", "last_seen_at": "..." } ],
  "total": 1 }
```

### `GET /engagements/{program_id}/assets/{asset_id}`
One asset with its edges and everything joined to it — the query the graph exists for.

```json
{ "asset": { ... },
  "relationships": [ { "relationship": "exposes", "direction": "out", "other": { ... },
                       "confidence": "confirmed", "source": "nmap" } ],
  "counts": { "recon": 12, "scans": 3, "services": 2, "findings": 1 } }
```

**Relationship verbs:** `resolves_to`, `hosted_on`, `exposes`, `discovered_from`, `belongs_to`, `vulnerable_to`.

**Errors** — `404` asset not found, or engagement not accessible.

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

### `POST /engagements/{program_id}/scope/import`
Import many scope items from a program's scope CSV, instead of adding them one at a time.

**Request body**
```json
{ "csv": "identifier,asset_type,...\nacme.com,URL,...", "format": "hackerone", "commit": false }
```
- `csv` — the raw text of the export (HackerOne scope CSV; it must have an `identifier` column).
- `format` — `hackerone` (the only preset today).
- `commit` — `false` (default) returns a preview and writes nothing; `true` inserts the new items.

Each row maps to a scope item: `asset_type` picks the `kind` (URL by shape, `WILDCARD`→domain, `API`→api, `CIDR`→cidr, the app-id types→mobile; the original type is kept in the note), `eligible_for_submission: false` makes it out-of-scope, and `max_severity` becomes the item's advisory severity cap. Rows whose identifier is empty are ignored; rows with invalid characters or an over-long identifier are reported under `skipped`. Nothing is ever deleted, so re-importing an updated export only adds what is new.

**Response**
```json
{
  "format": "hackerone", "committed": true, "created": 5,
  "summary": { "in": 4, "out": 1, "duplicates": 2, "skipped": 1, "total_rows": 8 },
  "new_items": [ { "value": "acme.com", "kind": "domain", "scope_type": "in", "max_severity": "critical", "notes": "HackerOne URL" } ],
  "duplicates": [],
  "skipped": [ { "line": 7, "identifier": "...", "reason": "invalid characters" } ]
}
```

- `400` — the CSV has no `identifier` column, or exceeds the row limit.

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

### Finding history and activity

Every create and update of a finding appends an immutable snapshot, so the finding's history is
kept even as the live record changes. The first update of a finding that predates this feature
first records a `baseline` snapshot of its prior state. Snapshots and notes are passed through the
secret redactor before they are stored. Deleting a finding deletes its history; the audit log keeps
the record that it happened.

### `GET /engagements/{program_id}/findings/{finding_id}/activity`
The finding's timeline, newest first. Query: `limit` (1-200, default 50), `offset`.

```json
{
  "activities": [
    { "id": "<uuid>", "kind": "retest", "outcome": "verified_fixed", "notes": "...",
      "actor": "<github_id>", "created_at": "2026-10-09T01:00:00",
      "snapshot": { "...": "the finding as it stood" },
      "evidence": [ { "id": "<uuid>", "title": "Retest output", "content_hash": "<sha256>" } ] }
  ],
  "total": 1, "offset": 0, "limit": 50
}
```
`kind` is `created`, `updated`, `baseline`, `remediation`, or `retest`.

### `POST /engagements/{program_id}/findings/{finding_id}/activity`
Record a remediation note or a completed retest. Members and owners only (viewers get `403`).

| Field | Type | Notes |
|---|---|---|
| `kind` | `remediation` or `retest` | required |
| `notes` | string | required, 1-10000 chars; HTML stripped |
| `outcome` | `still_open`, `partially_fixed`, `verified_fixed`, `inconclusive` | **required for a retest, rejected for remediation** (`400`) |
| `evidence_ids` | string[] (max 50) | existing evidence on this finding; each is recorded with its title and SHA-256 so integrity survives later retention |

Returns the new entry (`201`). A verified retest does **not** change the finding's status. `404` for
an unknown finding or evidence that does not belong to it.

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
`title` is required. `finding_id` is optional — reports can exist without a linked finding. `status` values: `draft`, `internal_review`, `final`, `delivered`, `archived`.

A report is a client deliverable, so the statuses describe where the document is on its way to the client. The common path is `draft → internal_review → final → delivered`.

**Transitions are not enforced.** These are independent workflow labels: any status may be set at creation or on update, in any order. A report can be created directly as `delivered`, moved from `delivered` back to `draft` after client feedback, or `archived` from any point. The API validates only that the value is one of the five.

The retired bounty-submission values (`submitted`, `accepted`, `duplicate`, `informative`, `resolved`) are rejected with `422`; migration `0022reportlifecycle` maps stored rows.

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

## Engagement Deliverables

Client-facing reports assembled from the engagement's testing record. Each save creates a new
**immutable revision**: a frozen snapshot of the scope, authorizations, selected findings and
evidence, and remediation/retest history, plus its rendered Markdown and a SHA-256 of that
Markdown. Only the workflow `status` of a revision changes after it is created. The whole snapshot
is passed through the secret redactor and capped at 4 MiB (`413` above that). Evidence is rendered
as indented blocks so target-controlled text cannot break out of the report.

### `GET /engagements/{program_id}/deliverables`
List deliverables, newest first. Query: `limit` (1-200, default 50), `offset`.
`{ "deliverables": [ { "id", "title", "latest_revision", "created_at" } ], "total": 1 }`

### `POST /engagements/{program_id}/deliverables`
Create a deliverable and its revision 1 (`201`). Members and owners only.

| Field | Type | Notes |
|---|---|---|
| `title` | string | required, max 200 |
| `executive_summary`, `methodology`, `limitations`, `remediation_priorities` | string | each max 20000; HTML stripped |
| `finding_ids` | string[] or null | `null` (default) includes **all** findings at save time; `[]` includes none |
| `evidence_ids` | string[] (max 100) | evidence to copy into the revision; must not belong to an omitted finding (`400`) |

`404` if a listed finding or evidence item is not in this engagement.

### `POST /engagements/{program_id}/deliverables/{report_id}/revisions`
Save a new revision (`201`). Same body as create plus **`base_revision`** (required): the revision
the edit started from. If it is not the latest, the request fails with `409` and nothing is saved,
so concurrent edits cannot silently overwrite each other.

### `GET /engagements/{program_id}/deliverables/{report_id}/revisions`
Revision list without content. Query: `limit`, `offset`.

### `GET /engagements/{program_id}/deliverables/{report_id}/revisions/{revision}`
One revision with its `snapshot` and `markdown`.

### `GET /engagements/{program_id}/deliverables/{report_id}/revisions/{revision}/markdown`
The Markdown as a `text/markdown` download.

### `PATCH /engagements/{program_id}/deliverables/{report_id}/revisions/{revision}`
Set the revision's workflow `status` (`draft`, `internal_review`, `final`, `delivered`, `archived`).
Content is never edited; to change it, save a new revision.

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
List recon items for a engagement, with optional filters. Items come from ffuf, httpx, katana, and gau imports (and subfinder/dnsx via httpx-format uploads).

**Query parameters**
| Parameter | Default | Constraints | Description |
|---|---|---|---|
| `limit` | 100 | 1–500 | Max items to return |
| `offset` | 0 | ≥0 | Number of items to skip |
| `search` | (none) | — | Full-text filter across URL, host, path, title |
| `status_code` | (none) | — | Filter by HTTP status code (e.g. `200`) |
| `source` | (none) | max 30 chars | Only items from this tool (`httpx`, `katana`, `gau`, `ffuf`); case-insensitive |
| `job_id` | (none) | — | Items this job **observed**, including rows an earlier job first created (job result links) |

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
List scan items with pagination and optional status filter. Items come from nuclei and dalfox imports.

**Query parameters**
| Parameter | Default | Constraints | Description |
|---|---|---|---|
| `limit` | 100 | 1–500 | Max items to return |
| `offset` | 0 | ≥0 | Number of items to skip |
| `status` | (none) | — | Filter by status value |
| `job_id` | (none) | — | Only items this scan job saw: the ones it first produced **plus** ones an earlier job had already stored that this run observed again. Matches `/recon` and `/services`. **Changed in v0.41.0** — it previously returned only items the job produced, so a deduplicated re-scan appeared to have found nothing |

Each item carries the scanner's own verification signal alongside severity: `type` (the
scanner's classification of the match — for dalfox its tier: `vulnerable`, `reflected`,
`ast`, `informational`), `detection_method` (dalfox: `reflection`, `dom-verification`,
`ast`, `oob`, `library`) and `confidence` (`high`/`low`), plus the scanner's `payload` and `match_evidence` exactly as reported (untrusted text; render only as text). These are independent of severity
and of each other, and none of them is a confirmation: imported matches are always
`status: "new"`, and promoting one is an operator's act.

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
      "detection_method": "",
      "confidence": "",
      "payload": "",
      "match_evidence": "",
      "job_id": "<uuid | null>"
    }
  ],
  "total": 55,
  "offset": 0,
  "limit": 100
}
```
`job_id` is the scan job that produced the item (null for manual file imports), enabling a job → its-results provenance link.

`detection_method` and `confidence` are empty for sources that report neither (nuclei today). A dalfox item looks like:

```json
{
  "source": "dalfox",
  "template_id": "inHTML:q",
  "title": "XSS in parameter 'q' (inHTML)",
  "severity": "high",
  "type": "vulnerable",
  "detection_method": "dom-verification",
  "confidence": "high",
  "cwe": "CWE-79",
  "status": "new"
}
```

`template_id` is the injection context and parameter — dalfox has no template id, and this pair is what identifies the same issue across runs, so the importer dedupes on it.

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
| `tool_type` | string | `ffuf`, `httpx`, `nuclei`, `katana`, `gau`, or `dalfox` |
| `file` | file | `.json` or `.jsonl` output file |
| `job_id` | string (optional) | Scan job that produced this output. **Must be a job of this engagement, otherwise `404` and nothing is imported** (a made-up id, or another engagement's job, is refused). Stamped onto new rows, and every row the job observed - including ones that already existed - is linked to it. VardrRunner passes the id of the job it is executing. |

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
- `tool_type`: `"httpx"`, `"nuclei"`, `"subfinder"`, `"nmap"`, `"dnsx"`, `"naabu"`, `"katana"`, `"gau"`, `"ffuf"`, `"dalfox"`, or `"vardrgate_api_test"`
- `target_source`: `"scope"` or `"recon"`
- `config` (optional): tool-specific options. Unknown keys are rejected.

  | Tool | Config keys |
  |---|---|
  | `httpx` | `status_code`, `limit`, `rate` (1–1000, requests/sec), `headers` |
  | `nuclei` | `severity`, `templates`, `rate` (1–1000, requests/sec), `headers` |
  | `subfinder` | `recursive`, `sources` |
  | `nmap` | `top_ports` (1–65535), `timing` (0–4) |
  | `dnsx` | `limit` (1–1000000), `timeout` (1–86400 s) |
  | `naabu` | `top_ports` (1–65535), `limit` (1–1000000), `timeout` (1–86400 s) |
  | `katana` | `depth` (1–10), `js_crawl` (`true`/`false`), `limit` (1–1000000), `status_code`, `timeout` (1–86400 s), `rate` (1–1000, requests/sec), `headers` |
  | `gau` | `subs` (`true`/`false`), `providers` (any of `wayback`, `commoncrawl`, `otx`, `urlscan`; comma string or list), `timeout` (1–86400 s) |
  | `ffuf` | `wordlist` (a **name**, see below), `extensions` (`.php,.bak`; comma string or list, a bare `php` gains its dot), `match_codes` (three-digit statuses, or `all`), `rate` (1–1000, requests/sec **per target**), `limit` (1–1000000), `timeout` (1–86400 s), `headers` |
  | `dalfox` | `limit` (1–1000000), `status_code`, `worker` (1–100, concurrency), `delay` (0–10000 ms between requests), `mining` (`true`/`false`, discover parameters), `timeout` (1–86400 s), `headers` |
  | `vardrgate_api_test` | `test_case_id` (required), `timeout` |

  Integer bounds mirror the ones VardrRunner enforces, so an out-of-range value is refused at queue time rather than failing on the operator's machine after the job is claimed.

  **`rate` caps requests per second** for the tools that send live traffic to a target. Omitting it keeps the tool's own default. When the engagement sets `max_request_rate`, an explicit `rate` above it is refused and a job with no `rate` has the ceiling applied (never above the tool's default), so the ceiling binds either way. `ffuf` keeps its separate always-on rate cap.

  **`headers` adds custom request headers** — the identification header some programs ask researchers to send — as an object `{"Name": "value"}` or a list `["Name: value", …]`, up to 20. A name must be an HTTP token and a value may not contain a control character, so a job config cannot inject a second header or a request line. Accepted for `httpx`, `nuclei`, `katana`, `ffuf` and `dalfox`.

  **`ffuf.wordlist` is a name, never a path.** It must match `[a-z0-9][a-z0-9_-]{0,39}` — `common`, `api-paths`. VardrRunner resolves that name against `~/.vardrmap/wordlists` on the machine running the scan. A path, a traversal, or a drive letter returns `400`. This is deliberate: were a path accepted, this API could name any file the runner can read, and ffuf would read it and replay its lines at a target. The runner refuses a path too, so accepting one here would only queue a job that cannot run.

  **`ffuf.limit` counts recon rows, not hosts.** VardrRunner collapses ffuf's targets to site roots *after* the limit is applied, so 100 recon URLs that all live on one host consume the default limit and fuzz a single root. Raise `limit`, or use `target_source: "scope"`, when a recon table is dense on few hosts. For the same reason `POST /jobs/preview` reports the resolved recon targets rather than the roots ffuf will fuzz, so for `ffuf` its `count` is an **upper bound** on the hosts touched, not the exact execution set.

  **`ffuf.rate` is a safety control, not a tuning knob.** It bounds the load a job can put on a client's host, so it has a ceiling and no value meaning "unlimited"; omitting it gives VardrRunner's default of 50/s. ffuf additionally always runs with auto-calibration, so a host that answers every path with `200` cannot flood recon with phantom endpoints.
- `depends_on` (optional): id of another job (same engagement) that must reach `done` before this job becomes eligible in `GET /jobs/pending`.

**Response:** job object with `status: "pending"`.

**Errors**
- `400` — invalid `tool_type`, invalid `target_source`, unknown config key, or `depends_on` referencing a job not in this engagement
- `404` — engagement not found or belongs to another user

### `POST /engagements/{program_id}/pipelines`
Queue an ordered chain of jobs where each stage waits on the previous one. The UI's named chains — Attack Surface (`subfinder → dnsx → httpx → nuclei`) and Host Enumeration (`naabu → nmap → httpx`) — are each one request. Validation is per-stage and identical to single-job creation, so a bad stage rejects the whole pipeline atomically (no partial writes).

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

`depends_on` is linked sequentially over whatever stages arrive, so any ordered subset is valid — posting just `subfinder` and `nuclei` chains those two directly, with no dangling wait on the omitted stage. The Composer's stage editor relies on this: it posts only the stages the operator included.

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
List jobs for an engagement, newest first.

| Query | Default | Description |
|---|---|---|
| `status` | (all) | `pending`, `running`, `done`, or `failed` |
| `limit` | (all) | 1-500. **Omitted = every job**, so the job board is unchanged |
| `offset` | 0 | rows to skip |

**Response**
```json
{ "jobs": [ <job_object>, ... ], "total": 12, "limit": null, "offset": 0 }
```
`total` counts the jobs matching `status`, regardless of paging.

### `GET /jobs/pending`
Return `pending` jobs in engagements accessible with write permission to the authenticated user that are eligible to run now, oldest first. Read by `vardrrunner jobs run`, which executes what it returns once and exits; nothing polls in the background.

Pipeline stages with an unmet dependency are held back: a job with `depends_on` set is only returned once its parent reaches `done`. If the parent `failed` (or no longer exists), the dependent job is auto-failed with an `"upstream pipeline stage failed"` message so it never hangs the queue.

**Response**
```json
{ "jobs": [ <job_object>, ... ] }
```

**VardrGate jobs get their spec inlined.** A `vardrgate_api_test` job stores only `config.test_case_id`. In this response — and only in this response — the stored spec is expanded into `config.test_case`:

```json
{
  "tool_type": "vardrgate_api_test",
  "config": {
    "test_case_id": "<uuid>",
    "test_case": { "id": "bola-check", "identities": [ ... ], "request": { ... } }
  }
}
```

That keeps `scan_jobs.config` flat for validation while giving the runner the object its config parser requires. The expansion is never written back, so revising a case changes what the next hand-off carries. A job whose case has been deleted is auto-failed with `"authorization test case ... no longer exists"`.

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

### `POST /jobs/{job_id}/upload`

Receive a VardrGate result for a `vardrgate_api_test` job. Posted by VardrRunner after the tool runs; accepts one `engine.Result`.

**Request body**
```json
{
  "test_case_id": "bola-check",
  "executions": [
    { "identity_id": "attacker", "status_code": 200, "observed_outcome": "allow",
      "duration_ms": 39, "headers": { "Content-Type": "application/json" } }
  ],
  "findings": [
    { "category": "potential_bola", "severity": "high", "confidence": "high",
      "identity_id": "attacker", "message": "attacker read another user's profile",
      "evidence": ["expected deny, observed allow (200)"],
      "detected_at": "2026-08-17T10:00:00Z" }
  ]
}
```

**Where the result lands**

| Result field | Becomes | Notes |
|---|---|---|
| `findings[]` | `scan_items` with `source="vardrgate"` | Reuses the triage and promote-to-finding flow nuclei results already use rather than a parallel one |
| `findings[].category` | `scan_items.type` | `potential_bola`, `cross_tenant_access`, `privilege_escalation`, … |
| `findings[].severity` | `scan_items.severity` | Same `info…critical` set as everywhere else; an unrecognised value falls back to `info` rather than being guessed upward |
| `test_case_id` | `scan_items.template_id` | The role a nuclei template id plays |
| the case's `request.url` | `scan_items.asset` / `matched_at` | Read from the stored case, not the payload |
| `executions[]` | `evidence` with `kind="tool_result"` | Content-hashed, `sensitivity="confidential"`, one row per identity |

When supplied by VardrGate, `executions[].response_profile` is retained inside
the evidence body. It describes response structure without storing the response
body and remains an upstream-owned, extensible object.

Everything is **redacted on write**. VardrGate excludes credential values and response bodies from its own JSON (`json:"-"`), but a control that depends on the sender behaving is not a control.

Findings land with `status: "new"`, so they appear in the Scanning section for triage like any other machine-generated result.

**Response**
```json
{ "job_id": "<uuid>", "scan_items_created": 1, "evidence_created": 2, "already_processed": false }
```

The first accepted result creates an idempotency receipt. Retrying the identical
payload returns the same counts with `already_processed: true` and creates no
new rows. A different second payload returns `409`. The payload's
`test_case_id` must match the VardrGate id on the case queued for the job.

**Errors**
- `400` — the job is not a `vardrgate_api_test` job, or the result names a different test case
- `401` — not authenticated
- `403` — viewer-role member (read-only)
- `404` — job not found or not accessible
- `409` — a different result was already accepted for this job
- `413` — result payload exceeds 512 KB

### `GET /jobs/{job_id}/events`
Frontend polls this to stream job lifecycle events into the Terminal. Returns events in chronological order. Optional `limit` (1-500) and `offset` page through them; omitting `limit` returns every event. The response also carries `total`, `limit` and `offset`.

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
List services for a engagement, ordered by host then port. Optional `job_id` returns only the services that job observed.

**Response**
```json
{ "services": [ <service_object>, ... ], "total": 42 }
```

### `POST /engagements/{program_id}/services`
Bulk-upsert services. VardrRunner posts nmap results here after a scan job completes. Upserts on `(host, port, protocol)` — updates metadata if the combination already exists. Optional body field `job_id` links every service in the request (new or updated) to the job that observed it; it must be a job of this engagement or the request fails with `404`.

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
| `tool_type` | string | yes | `httpx`, `nuclei`, `subfinder`, `nmap`, `dnsx`, `naabu`, `katana`, `gau`, `ffuf`, `dalfox`, or `vardrgate_api_test` |
| `target_source` | string | yes | `scope` or `recon` |
| `config` | object | no | Tool config, same validation as job creation |

**Errors**
- `400` — invalid tool, source, or config keys
- `403` — viewer-role member (read-only)
- `404` — engagement not found or belongs to another user

### `DELETE /engagements/{program_id}/scan-profiles/{profile_id}`
Permanently delete a profile.

---

## Authorization Test Cases

Stored [VardrGate](https://github.com/VardrSec/VardrGate) authorization test cases, scoped to an engagement. A case describes one request replayed as several identities, with the access decision expected of each — the input to a BOLA / BFLA / cross-tenant / privilege-escalation check.

A case is stored once and referenced from a job by id, so `ScanJob.config` stays flat (`{"test_case_id": "<uuid>"}`), one case can back many runs, and editing a case does not require re-queueing.

`spec` holds VardrGate's own `AuthorizationTestCase` JSON verbatim — VardrGate owns that schema. Before storage, VardrMap mirrors the engine's execution-critical validation: identity and credential consistency, request shape, explicit `mutating: true` for unsafe requests/setup, expected decisions, denial statuses, setup references, and resource owner/role references. This prevents a case that is already known to be invalid from reaching a runner.

### Credentials are references, never values

**A credential carrying a non-empty literal `value` is rejected with `400`.** Each identity must reference its secret with `value_env` (an environment variable read on the runner) or `value_keychain` (an OS keychain account), which VardrRunner resolves on the operator's machine. The secret never reaches VardrMap and is never stored.

An empty `value` is allowed — `{"type": "static_header", "header": "", "value": ""}` is the legitimate anonymous caller in a BOLA case.

`credential.type` is `bearer`, `api_key_header`, or `static_header`. `bearer` and `api_key_header` require exactly one secret reference; `static_header` may have none.

### `GET /engagements/{program_id}/test-cases`
List the engagement's test cases, newest first.

**Response:** `{ "test_cases": [ <test_case_object>, ... ] }`

### `POST /engagements/{program_id}/test-cases`
Store a test case.

**Request body**
```json
{
  "name": "BOLA — user profile",
  "description": "",
  "spec": {
    "id": "bola-resource-ownership-check",
    "identities": [
      { "id": "admin",     "credential": { "type": "bearer", "value_env": "ADMIN_TOKEN" } },
      { "id": "attacker",  "credential": { "type": "bearer", "value_keychain": "attacker-token" } },
      { "id": "anonymous", "credential": { "type": "static_header", "header": "", "value": "" } }
    ],
    "request": { "method": "GET", "url": "https://api.example.com/users/42/profile" },
    "expected_access": [
      { "identity_id": "admin",     "decision": "allow" },
      { "identity_id": "attacker",  "decision": "deny" },
      { "identity_id": "anonymous", "decision": "deny" }
    ]
  }
}
```

**Response:** `201` test case object.

**Errors**
- `400` — malformed spec, or a credential carrying a literal `value`
- `403` — viewer-role member (read-only)
- `404` — engagement not found or not accessible

### `GET /engagements/{program_id}/test-cases/{test_case_id}`
Fetch one. `404` if it belongs to another engagement.

### `PATCH /engagements/{program_id}/test-cases/{test_case_id}`
Update `name`, `description`, or `spec`. A replaced spec is validated identically to create — including the credential rule — and refreshes the surfaced `test_case_id`.

### `DELETE /engagements/{program_id}/test-cases/{test_case_id}`
Permanently delete a case.

**Test case object**
```json
{
  "id": "<uuid>",
  "program_id": "<uuid>",
  "name": "BOLA — user profile",
  "test_case_id": "bola-resource-ownership-check",
  "description": "",
  "spec": { "...": "VardrGate AuthorizationTestCase JSON" },
  "created_at": "2026-08-16T12:00:00",
  "updated_at": null
}
```

`test_case_id` is VardrGate's own id from `spec.id`, surfaced so a result can be traced back without opening the blob. It is not unique — a case may be revised.

### Drafting cases

Cases can be **drafted** from observed API operations or an OpenAPI document, then saved only after
a human reviews them. Drafting never stores or queues anything, never copies credentials, request
bodies, examples or security values from its input, and never infers who *should* have access: every
generated access decision is `skip`.

### `POST /engagements/{program_id}/test-cases/preview`
Generate draft cases. Provide **exactly one** of `endpoint_ids` (API-surface operations of this
engagement, max 100) or `openapi` (an inline OpenAPI 3.x JSON object, max 2 MiB; `$ref`s are
rejected, never fetched). Also `base_url` (absolute http/https, no credentials, query or variables;
required for OpenAPI documents without a `servers` entry), `limit` (1-100, default 50), `offset`.

```json
{ "drafts": [ { "name": "GET /users/{id}", "description": "...", "spec": { "...": "..." } } ],
  "total": 12, "offset": 0, "limit": 50, "next_offset": null,
  "review_notes": ["No cases have been stored or queued.", "..."] }
```
Each draft has an `anonymous` and a `member` identity (the member's token is a `value_env`
reference, never a value). `404` for endpoint ids not in this engagement.

### `POST /engagements/{program_id}/test-cases/reviewed`
Save drafts after review (`201`). Members and owners only. The body must carry **`"reviewed": true`**
and 1-100 `cases`. Each case is validated like a normal create, and additionally must have a
concrete http(s) URL (no credentials, fragments, whitespace or `{variables}`), exactly one access
decision per identity, and at least one that is `allow` or `deny`. Nothing is queued; run a saved case
from the job composer.

### Running a case

Queue a `vardrgate_api_test` job referencing the case by id:

```json
{ "tool_type": "vardrgate_api_test", "target_source": "scope",
  "config": { "test_case_id": "<uuid>" } }
```

Only the reference is stored. `GET /jobs/pending` **inlines the stored spec** as `config.test_case` when handing the job to a runner, which is what VardrGate's config parser expects — so job config stays flat for validation while the runner receives a full object. The expansion exists only in that response; `scan_jobs.config` keeps holding just the id, so editing a case changes what the next run receives.

A job whose case has since been deleted is auto-failed rather than handed over — it can never succeed, and leaving it pending would hang the queue.

Results come back via [`POST /jobs/{job_id}/upload`](#post-jobsjob_idupload).

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
The response now includes `new_count` for httpx, ffuf, katana, and gau imports — the number of recon items that were not previously seen for this engagement. Re-importing the same file a second time will produce `imported_count: 0, new_count: 0`. A new `first_seen_at` timestamp is set on each unique recon item at discovery time and never overwritten. A webhook fires (if configured) when `new_count > 0` for httpx imports.

**katana** imports accept VardrRunner's compact records (`url`, `status_code`, `content_length`, `content_type`) or katana's own JSONL (`request.endpoint`, `response.*`); response bodies are never read or stored. **gau** imports take `{"url": ...}` per line. For both, only `http`/`https` URLs are kept (archives routinely include `mailto:`, `javascript:`, and malformed entries), host and path are derived from the URL, and duplicates are dropped both against stored rows and within the upload.

**URL fields are stored exactly as the tool reported them** (`url`, `host`, `path` for httpx, ffuf, katana and gau; `asset`/`matched_at` for nuclei): control characters are removed and length is capped at 8192, and `<`/`>` are percent-encoded (`%3C`/`%3E`) so a URL is never stored as markup. `&` is **not** encoded, so `?a=1&b=2` round-trips and is what a runner scans when it reads recon back as targets. Titles and other descriptive text are still sanitised. **Rows imported before v0.43.0 may hold `&amp;` where the URL had `&`**; they are not rewritten, because several different originals collapsed to the same stored value (see `docs/recon-url-recovery-plan.md`). Re-importing such a URL adds the correct row beside the old one, except httpx, which matches by host and corrects its row in place on the next probe.

**dalfox** imports accept its `-f json` document (findings under `findings`, beside a `meta` envelope) or those objects as JSONL, and land as **scan items with `status: "new"`** — candidates, not findings. The scanner's own signal is preserved: its tier in `type` (`vulnerable`/`reflected`/`ast`/`informational`), plus `detection_method` and `confidence`. Even its top tier means *dalfox* asserts exploitability, so nothing here is imported as confirmed; promoting a candidate stays an operator's act, and a value dalfox does not define is dropped rather than stored. `request`/`response` (present with `--include-all`) are ignored, so response bodies are never stored. The **payload, the evidence and the PoC URL are stored exactly as dalfox reported them** (control characters removed, 2000-character cap), in the `payload`, `match_evidence`, `asset` and `matched_at` fields. They are deliberately *not* HTML-sanitised: the sanitiser deletes anything tag-shaped and HTML-encodes `&`, which turned `<svg onload=alert(1)>` into nothing and `?a=1&q=x` into `?a=1&amp;q=x`, destroying the one thing a tester needs to reproduce the issue. They are **untrusted text and must only ever be rendered as text**. Only the human-readable `description` goes through the sanitiser; it points at the payload column rather than quoting it. A PoC URL that is not `http(s)` is dropped.

Unlike nuclei, dalfox imports are **deduplicated** — a re-scan re-reports every match it still finds, which would otherwise inflate the engagement's count on every run. The key is the URL without its query values, the injection context and parameter (`template_id`), and the tier; it deliberately excludes the payload and the PoC URL, because dalfox mints a fresh marker class per payload and both carry it. A tier change (reflected → vulnerable) is new information and is stored as its own row. Deduplicated matches still get a provenance link, so `GET /scans?job_id=` shows that the later job observed them.

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

Clients are accessible to their creator and organization members. They are **not**
shared through engagement invitations alone. Organization viewers can read them;
PATCH and DELETE require direct ownership or organization member-level write
access (otherwise `403`). Unrelated users receive `404`.

### `GET /clients`
List accessible clients, ordered by name.

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

## Agent proposals

A change an MCP agent proposes but cannot apply: a scope item, an authorization, or the
engagement's request-rate ceiling. The VardrRunner MCP server exposes tools to *propose* one
but **no tool to approve one** — a proposal is inert until a human with a full-access key
approves it here, which is what applies the change. This is the guardrail that keeps a
prompt-injected agent from widening its own scope or authorization: the worst it can do is
create a pending row the operator sees, with its stated reason and source, and rejects.

`reason` and `source` are the agent's own words. Treat them as untrusted display text.

### `GET /engagements/{program_id}/proposals`
List proposals, newest first. Optional `?status=pending|approved|rejected`. Readable by any
member, so an agent can see what is already pending and avoid duplicates.

**Response:** `{ "proposals": [ proposal, ... ] }`

### `POST /engagements/{program_id}/proposals`
Create a pending proposal. Inert, so member-write is enough — a runner-scoped key may call
it. `payload` is validated for the `kind`, reusing the scope/authorization sanitisers, so
only clean values are stored.

**Request body**
```json
{
  "kind": "scope_in",
  "payload": { "value": "branch.remitly.com", "kind": "domain", "max_severity": "critical" },
  "reason": "Listed in the HackerOne scope table",
  "source": "https://hackerone.com/remitly"
}
```
`kind` is `scope_in`, `scope_out`, `authorization` or `rate_ceiling`. `payload` matches the
corresponding create body: a scope item (`value`, `kind`, `notes`, `max_severity`), an
authorization (same fields as `POST .../authorizations`), or `{ "rate": <1–1000> }`. A bad
payload is refused (`400`, or `422` for an unparseable date). Beyond 100 pending proposals
the endpoint returns `409`.

**Response:** `201` proposal object, `status: "pending"`.

### `POST /engagements/{program_id}/proposals/{proposal_id}/approve`
Approve a pending proposal, applying the change (creates the scope item or authorization, or
sets the ceiling). **Full-access key only** (`403` for a runner-scoped key) — this is the
operator action an agent must not be able to take. A non-pending proposal returns `409`.

**Response:** proposal object, `status: "approved"`, with `applied_resource_id` set for a
scope/authorization approval.

### `POST /engagements/{program_id}/proposals/{proposal_id}/reject`
Reject a pending proposal without applying it. Full-access key only.

**Response:** proposal object, `status: "rejected"`.

---

## API Surface (Burp integration)

These routes require a browser JWT or a full-scope personal API key. Every
resource is scoped to the authenticated operator's engagement; cross-user reads
return `404`.

### `POST /engagements/{program_id}/api/exchanges`

Promote one selected HTTP exchange. Required fields are `method` and an absolute
HTTP(S) `url`. Optional fields are `path_template`, `source_tool` (`proxy`,
`repeater`, `intruder`, `scanner`, `organizer`, or `unknown`), `identity_label`,
request/response headers and bodies, response metadata, `note`, and
`captured_at`. Header/body fields are limited to 200,000 characters each.

The URL query and fragment are never stored. If `path_template` is omitted,
integer, UUID, and long opaque path segments become placeholders. Credentials
are redacted before storage. Returns `201` with `endpoint` and `exchange`.

### `GET /engagements/{program_id}/api/endpoints`

List canonical operations. Supports `search`, `method`, `limit` (maximum 500),
and `offset`. Each row includes observed status codes, identity labels, and an
observation count.

### `GET /engagements/{program_id}/api/endpoints/{endpoint_id}`

Return an operation with retained, redacted exchanges. Supports `limit` (default
50, maximum 200) and `offset`; `exchange_total` reports the unpaginated count.

### `DELETE /engagements/{program_id}/api/exchanges/{exchange_id}`

Delete one retained exchange and decrement its operation's observation count.

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
# Integration contract updates

`POST /engagements/{program_id}/evidence/{evidence_id}/link` accepts
`{"finding_id": "..."}` and returns the existing evidence with its new association.
This is an explicit reviewed write: the caller needs member-level write access.
Both objects must belong to this engagement; inaccessible or missing objects
return 404, viewers receive 403, and unauthenticated/invalid credentials receive
401. Linking again to the same finding is idempotent. Linking evidence already
associated with a different finding returns 409. It does not copy evidence or
change its body, hash, source, collector, or creation timestamp. A successful new
link is audited and permits using that evidence ID in finding activity/retests.

VardrGate job `config.timeout`, when supplied, must be an integer from 1 to 86400
seconds; VardrRunner applies it to Gate execution and the subprocess timeout.
Private-target access is opted into locally using the runner's
`VARDRRUNNER_ALLOW_PRIVATE_TARGETS=1` environment setting, never by queued config.
The backend continues to serialize `program_id`; runners normalize that wire
field to their internal engagement ID.

`POST /jobs/{job_id}/upload` accepts legacy Gate `findings: null` as `[]`, as well
as omitted/empty findings. Other malformed findings shapes still return 422.
This compatibility handling does not reinterpret execution failures as clean
scans; the worker still fails unsuccessful Gate processes.

`POST /jobs/{job_id}/events` also accepts `target_stats`, `target_warning`, and
`blocked`, retaining the existing lifecycle event types and access checks.

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

## API playbook guidance and Gate assessments

`GET /engagements/{id}/playbooks` returns `{playbooks, total}` with three summaries
(`id`, `title`, `version`, `use_when`). `GET /engagements/{id}/playbooks/{playbook_id}`
returns a guide plus `prerequisites`, `expected_artifacts`, `steps`, `common_traps`
and `manual_remainder`. The original v1.0 catalog is API-01 ownership/tenant
separation, API-02 privileged functions, API-03 evidence/retest/handoff. Reads need
full-scope credentials or a browser JWT; viewers can read. Unowned engagements and
unknown guide ids return 404. Neither endpoint stores progress or queues work.

`POST /jobs/{id}/claim` freezes a Gate case snapshot and returns its exact spec
in `config.test_case`. Pending polls still reflect edits before claim. The snapshot
is separate from stored `config`, which continues to hold only a case UUID.
Legacy PATCH-to-running also freezes the snapshot. Runner refuses a changed spec
between poll and claim so it cannot execute a target set the operator did not see.

`POST /jobs/{id}/upload` accepts optional `case_hash` (64 lowercase hex chars): SHA-256
of the unresolved case spec serialized with Python JSON `sort_keys=True`,
`separators=(",", ":")`, UTF-8 and default `ensure_ascii=True`. Secrets resolved on
Runner must not enter this hash. A supplied hash conflicting with the claim snapshot
returns 400. A missing hash or snapshot is accepted for legacy compatibility, but
cannot establish a conclusive assessment. Existing receipt hashes remain replayable.

Job responses include nullable `assessment`, independent of `status`. Its fields:

| Field | Meaning |
| --- | --- |
| `status` | `conclusive` when every declared identity has one definite reported decision and a valid baseline; `partial` when some are evaluated; otherwise `inconclusive` |
| `evaluated`, `inconclusive`, `missing`, `skipped` | Identity counts; absent/duplicate expectations are skipped rather than guessed |
| `unexpected` | Execution rows whose identity is absent from the case |
| `baseline_valid` | At least one reviewed allow identity reports a valid allowed response, with a bound case snapshot |
| `candidate_findings` | Number of uploaded triage candidates, not confirmed findings |
| `case_id`, `case_ref`, `case_hash`, `case_snapshot_verified` | Stored case UUID, logical id, claimed spec hash and whether the uploaded hash matches |
| `identities`, `reasons` | Each identity's expectation, reported outcome, assessment state and machine-readable reasons |
| `preflight` | Session check status (`not_configured`, `passed`, `failed`, `inconclusive`), per-identity diagnostics and unexpected row count; optional on older assessments |

Definite decisions follow reported allow/deny and reviewed denial conventions.
429/503, redirects, errors, missing responses, duplicate executions and stale/denied
legitimate baselines cannot establish a clean authorization result. Even a
`conclusive` assessment can contain violation candidates: it describes completeness
of runner-reported outcomes, not independent verification or security coverage.
Old jobs have `assessment: null`; their results are unrecorded, not retrospectively
classified. Evidence for an unbound result retains an unknown expected decision.

New finding activity references and client report revisions retain structured
execution provenance along with evidence IDs and hashes. Existing immutable
revisions remain untouched.

### Identity/session preflight

Stored case identities may declare `preflight: {url, expected_status, json_fields}`.
The URL must be absolute HTTP(S) on the tested request's origin, without userinfo,
fragment or variable references; maximum 2000 UTF-8 bytes. `expected_status` must
be a 2xx integer. `json_fields` contains 1–8 nonempty case-sensitive dotted paths
mapped to expected scalar strings (200 UTF-8 bytes per path/value). An authenticated
local credential reference and identity id of at most 200 UTF-8 bytes are required.
Malformed declarations return 400 on normal/reviewed saves and updates. No new
auth permission is granted; existing writer/viewer and ownership rules apply.

`POST /jobs/{id}/upload` also accepts optional `preflight`, at most 100 records:
`{identity_id, status, reason, status_code}`. Status is `passed` or `failed`; reasons
are `identity_verified`, `credential_rejected`, `identity_mismatch`,
`unexpected_status`, `execution_error`. Status code is an integer 0–599 (0 for no
HTTP response). Extra response data is discarded; safe diagnostic evidence is
persisted with `phase: identity_preflight` and unknown expected/observed resource
decisions. Empty/absent preflight does not alter legacy receipt fingerprints.
Required missing/duplicate/inconsistent/unbound checks prevent a conclusive
assessment. A passed session check cannot substitute for a working allow baseline
against the tested resource. See [authoring and rollout](identity-preflight.md).

## Gate semantic assessment evidence

`POST /jobs/{id}/upload` additionally accepts `assessments` from Gate results.
Only declared value-free fields are retained: identity/expected/assessed decisions,
source/reason codes, credential-check status, write-readback status, execution and
assertion indices, and reader/status/strategy/environment provenance. Unknown
metadata and response values are dropped. JSON evidence includes these as
`scanner_assessments`; the job assessment exposes them alongside raw outcomes.

Semantic conclusions must match the claim-time reviewed case, expected identity,
assertion indices or verifier configuration. Missing, duplicate, conflicting or
unbound proof remains inconclusive. A raw 2xx is not evidence that a configured
assertion or write verifier passed. These are runner-reported conclusions, not
independent verification of a vulnerability. Credential checks are point-in-time
observations. Existing receipt replays that predate semantic retention remain
immutable no-ops; they do not retroactively gain evidence.

`execution_cancelled` and `reset_baseline_mismatch` retain Gate's inconclusive
verifier diagnostics. They do not establish a denied write. Validate coordinated
versions with the [strict semantic contract](../scripts/integration/README.md#semantic-evidence-and-version-compatibility)
before rollout; older Map backends may accept the upload without retaining these
conclusions, and older companions may lack independent reader/strategy support.
