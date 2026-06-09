# Security Testing Record

This document captures manual security testing performed on VardrMap during development. Tests were run directly against the deployed backend on Railway using Burp Suite Community Edition. The frontend was bypassed entirely — all requests were made at the HTTP level.

---

## Authentication

All protected API routes require a valid `Authorization: Bearer <token>` header. Tokens are issued by the backend after GitHub OAuth login completes. JWT claims include `sub` (GitHub ID), `iss`, `aud`, and expiry — validated on every request. Requests without a valid token return `401 Unauthorized`.

---

## Authorization — BOLA Testing

**Broken Object Level Authorization (BOLA / IDOR)** was tested manually using Burp Suite Repeater with two separate authenticated GitHub accounts.

**Test procedure:**
1. User A created a program via `POST /programs` — captured the returned UUID from the response
2. User B (authenticated with a different JWT) used that UUID in requests via Burp Repeater
3. Tested `PATCH` and cross-user read access using User B's token against User A's program ID

**Results:**

| Request | User | Response |
|---|---|---|
| `POST /programs` | User B | `200 OK` — own program created normally |
| `PATCH /programs/{user_a_id}` | User B | `404 Not Found` |
| `GET /programs/{user_a_id}` | User B | `404 Not Found` |

**Conclusion:**

The backend filters all program queries by both `program_id` and `owner_github_id` derived from the JWT. This is enforced at the database query level — a valid token from a different user returns 404 rather than exposing or modifying the resource. The 404 (not 403) is intentional to avoid confirming that the resource exists.

| Screenshot | Description |
|---|---|
| ![BOLA 200](bola-200.png) | User B creates own program (`POST /programs`) — `200 OK`, UUID captured for BOLA test |
| ![BOLA 404](bola-404.png) | User B attempts `PATCH` on User A's program UUID — `404 Not Found`, access denied |

BOLA isolation is also covered by automated tests in `backend/tests/test_programs.py` and `backend/tests/test_apikeys.py`.

---

## Input Testing

Tested using Burp Suite Intruder (Battering Ram / Sniper) and Repeater against the `name`, `platform`, and other string fields across multiple attack iterations.

**Payloads tested:**

```
<script>alert(1)</script>
<img src=x onerror=alert(1)>
<scr<script>ipt>alert(1)</script>
javascript:alert(1)
onload=alert(1)
onerror=alert(1)
<b>bold</b>
' OR 1=1 --
null bytes
oversized strings
```

**Results:**

| Payload | Field type | Response |
|---|---|---|
| `<script>alert(1)</script>` | Short (name) | `422` after fix — `200` pre-fix (stored, not executed) |
| `<img src=x onerror=alert(1)>` | Short (name) | `422` — rejected |
| `javascript:alert(1)` | Short (name) | `422` after fix — `200` pre-fix |
| `onload=alert(1)` | Short (name) | `422` after fix — `200` pre-fix |
| `<scr<script>ipt>alert(1)</script>` | Short (name) | `422` after bleach fix — bypassed regex-only pass |
| `<b>bold</b>` | Long (markdown) | `200` — tags stripped, text `bold` stored |
| `' OR 1=1 --` | Any | `200` — stored as plain text, not interpreted |

**Iterative fix process:**

Initial regex-based sanitization was bypassed by the obfuscated payload `<scr<script>ipt>alert(1)</script>`. The fix was iterated in two passes:

- **Pass 1 (regex):** Caught `<img onerror>` and standard tags — obfuscated variant still bypassed (200)
- **Pass 2 (bleach + pre-strip detection):** Detection runs on raw input before any stripping — obfuscated tag caught and rejected (422)

| Screenshot | Description |
|---|---|
| ![XSS pre-fix](xss-before-fix.png) | Pre-fix: `<script>`, `javascript:`, `onload=` all return `200` — payloads accepted |
| ![XSS partial](xss-partial.png) | Mid-iteration: `<img onerror>` now `422`, obfuscated `<scr<script>ipt>` still bypasses at `200` |
| ![XSS after fix](xss-after-fix.png) | Post-fix: obfuscated payload returns `422` — bleach + pre-strip detection closes the bypass |
| ![SQLi stored](sqli-stored.png) | SQLi payloads (`' OR 1=1 --`) return `200` — stored as literal strings, ORM prevents execution |

**Implementation notes:**

- Short identifier fields (`name`, `title`, `asset`) run injection detection on raw input before any stripping — prevents obfuscated tag bypass
- Long-form fields use `bleach.clean()` to strip all HTML while preserving markdown syntax
- SQLAlchemy ORM parameterizes all queries — SQL payloads are stored as inert strings

---

## Testing Methodology

- **Burp Suite Community Edition** — Intruder (Battering Ram + Sniper), Repeater (manual request manipulation)
- **Multi-account authorization testing** — two real GitHub accounts, separate authenticated sessions
- **Manual API testing** — direct HTTP manipulation bypassing the frontend entirely
- **Payload categories tested** — XSS, obfuscated XSS, event handler injection, SQLi, null bytes, oversized input
- **Iterative fix validation** — each sanitization pass re-tested with the same payload set to confirm coverage

Testing was performed manually and focused on core program endpoints. Nested resources (findings, scope items, reports) have BOLA coverage via automated tests but have not been manually fuzz-tested with the same payload set.
