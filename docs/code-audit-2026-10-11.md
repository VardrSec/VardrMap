# Code and documentation audit — 2026-10-11

## Scope and outcome

This audit covers the VardrMap repository: backend routes and access boundaries,
models and migrations, frontend authentication and rendering, import/notification/
AI flows, integration scripts, CI and project documentation. Repository-wide
inventory and static searches were combined with focused manual review of the
security-sensitive paths and regression tests. Runner and Gate contracts were
checked at the integration boundary; this is not a full independent audit of
either companion repository, or a guarantee that every possible flaw is absent.

The audit preserves the existing uncommitted PostgreSQL reliability and integration
changes on `codex/postgres-reliability`. Nothing was deployed or released.

## Confirmed issues fixed

| Issue | Evidence and correction |
|---|---|
| Signed JWTs without expiry were accepted | A regression reproduced HTTP 200 for a correctly signed token with no `exp`. JWT decoding now requires expiry, subject, audience and issuer; existing signature/claim validation remains. |
| Organization viewers could mutate shared clients | PATCH and DELETE reproduced successful writes by a viewer. Both handlers now require direct ownership or organization member-level write access; viewers retain read access. Unrelated users still receive 404. |
| Webhook DNS validation could be followed by a second hostname resolution | Delivery now connects to a validated public IP and retains the original HTTP Host and TLS SNI/verification identity. Environment proxies and redirects are disabled; malformed URLs, URL credentials and non-global addresses are rejected. |
| Webhook exception logging could reveal secret URL paths | Logs retain the error class rather than the full exception URL. |
| Import upload cap was checked after an unbounded read | Reads are capped at the existing limit plus one byte; oversize imports still return 413. This does not replace infrastructure multipart ingress limits. |
| AI helpers sent unredacted finding/scanner text and exposed provider errors | Shared heuristic redaction runs before provider calls. Errors return generic 502 details. Prompts identify evidence fields as untrusted and use engagement/pentest vocabulary. No autonomous execution authority was added. |
| Vulnerable transitive dependencies | Compatible frontend lockfile updates removed the critical Handlebars advisory and several other findings. urllib3 2.8.0 is explicitly pinned for Sentry's HTTP transport. Local pip tooling was updated and the backend environment aligned with the repository pins. |

Regression tests exercise JWT expiry, organization viewer/member behavior,
webhook address pinning and secret-safe errors, bounded upload reads and both AI
provider boundaries. A real loopback HTTPS test verified original Host/SNI delivery
and rejection of an incorrect TLS hostname; it did not disable certificate verification.

## Documentation reconciliation

- Corrected the browser's direct backend request flow, Auth.js callbacks and
  AppContext helper location. The Next.js middleware does not proxy backend calls.
- Replaced the stale schema inventory with the current ORM model/column inventory.
- Updated organization/client access, assets, evidence, test-case authoring,
  remediation/retests and client deliverable descriptions to implemented behavior.
- Corrected the eleven-tool and four-pipeline inventories and schedule tool lists.
- Distinguished stop-work's prevention of new execution from process cancellation.
- Replaced outdated current-backlog claims; labelled the implementation roadmap and
  old manual security results as historical rather than present verification.
- Removed absolute secret-free claims, distinguishing heuristic redaction, raw
  scanner evidence preservation, sensitivity metadata and actual enforcement.
- Strengthened API documentation coverage to require HTTP method plus route path.

## Verification

Final testing used the versions pinned in `backend/requirements.txt` rather than
the previously stale virtual environment.

| Check | Result |
|---|---|
| Backend, SQLite | 1,016 passed |
| Backend and migration tests, disposable PostgreSQL with TLS | 1,020 passed: 1,016 backend + 4 migration tests |
| Frontend Jest | 138 passed, 12 suites |
| Frontend lint / typecheck / production build | Passed after lockfile updates |
| Installed Python dependency audit / pip check | No known advisories / no dependency conflicts |
| npm audit after compatible updates | 25 development-package findings: 5 high, 20 moderate, 0 critical; no production dependency flagged |
| Bandit, backend and integration scripts excluding test/venv directories | 0 high; 4 medium SQL-construction findings use fixed migration identifiers; 13 low findings reviewed in context |
| New security regression modules, Ruff | Passed |
| Local documentation file links / diff whitespace | Passed |

The first SQLite run exposed a test cleanup issue: an intentional failed write
returned a connection with SQLite's connection-local read-only pragma to the pool.
The test now holds a dedicated connection until the pragma is restored. The
subsequent complete SQLite and PostgreSQL suites passed.

## Remaining findings and limits

1. **Development dependency advisories remain.** The remaining root advisories
   involve `braces` and `sprintf-js`, propagated through lint/test dependencies.
   npm proposes breaking downgrades of Next/Jest tooling. Those were not applied;
   a tooling migration needs its own compatibility assessment. These are advisory
   package counts, not 25 independently demonstrated product exploits.
2. **Text escaping can corrupt ordinary stored text (new writes fixed in the follow-up below).** Some long-form fields
   still use the sanitizer that encodes `&` as `&amp;`. Recon URLs have their
   separate preservation fix, but ordinary display text needs a deliberate lossless
   storage/rendering policy. Existing data cannot be blindly decoded. See
   [the recovery plan](recon-url-recovery-plan.md).
3. **Literal-credential protection has a defined boundary.** Stored test-case
   identity credential objects reject literal secrets, but arbitrary request
   headers, URLs and bodies can contain sensitive values. Review them before
   saving cases. Redaction is heuristic, not a proof of secret absence.
4. **PostgreSQL cleanup emits ORM warnings (resolved in the follow-up below).** Some engagement deletions delete
   result links through overlapping ORM/database cascades, producing expected-row
   count warnings. Tests pass, but the cascade ownership should be simplified in
   a focused change rather than suppressing the warnings.
5. **Operational protections have limits.** Tool rate limits apply per execution;
   no engagement-wide budget or running-process cancellation is claimed. Evidence
   retention labels do not automatically expire data. Webhook delivery is best-effort
   and uses one approved address; its HTTP timeout does not bound OS DNS resolution.
6. **Production and external paths remain unverified here.** Real GitHub OAuth,
   deployed tenant accounts, Railway/Vercel settings, live webhook providers,
   telemetry configuration and production database contents were not exercised.
   Burp extension source/contracts were inspected, not its full interactive workflow.

The default backend Ruff scan also reports existing conventions/style findings
(including FastAPI dependency defaults and intentional exception boundaries).
This audit does not claim the entire historical codebase is Ruff-clean or replace
those conventions with broad mechanical changes.

## Follow-up implementation

PR #85 commits the audit work. New sanitized text now preserves ampersands and
literal entities without changing existing HTML-removal rules or rewriting old
rows. The historical recon audit keeps its old transformation explicitly.
Observation-link relationships now give the ORM the dependency ordering needed
to avoid PostgreSQL cascade double-deletes; warnings are not suppressed.
Next.js lint configuration retains its working version: 16.4 enables additional
React effect rules requiring a separate UI refactor, so the compatible security
updates are kept without that rule migration. The remaining advisory
roots (`braces` 3.0.3 and `sprintf-js` 1.1.3) are still flagged at their latest
published versions; compatible updates cannot currently remove them.
The integration harness uses its declared httpx dependency instead of relying
on requests being incidentally installed locally.

Follow-up verification: 1,037 SQLite tests and 1,037 PostgreSQL backend tests plus
four migration tests pass. PostgreSQL runs treat SQLAlchemy warnings as errors;
no overlapping-cascade warnings remain. The final httpx-based staging-mode
Map → Runner → Gate acceptance run passes all 39 checks on a freshly migrated
PostgreSQL database. Hosted staging/OAuth remain pending a dedicated endpoint
and test credentials.
