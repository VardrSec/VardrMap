# Architecture

## Overview

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

Each section component (FindingsSection, ReportsSection, ManualSection) fetches its own full data set with a separate request when it mounts or after a mutation. The `onRefresh` callback from the parent re-fetches the program to keep the dashboard counts current.

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
