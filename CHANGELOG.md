# Changelog

All notable changes to VardrMap. Versions are tagged by milestone — this project does not use semver.

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
