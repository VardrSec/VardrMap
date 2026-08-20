# VardrMap — Implementation Roadmap

Tied to the actual repository. Baseline recorded 2026-08-12 on `main` @ `793ad79`:

| Check | Result |
|---|---|
| Backend `pytest` | 468 passed, 96% coverage |
| Backend `pip-audit` | clean (1 documented ignore: PYSEC-2026-1325) |
| `alembic heads` | `0015dropsubmissions` — single head |
| Frontend `typecheck` / `lint` | clean |
| Frontend `jest` | 63 passed |
| `npm audit --audit-level=high` | 0 vulnerabilities |

## Sequencing decision — why Phase 1 is split

The brief bundles "Organizations and RBAC" with "central scope evaluator, stop-work,
audit log" as one phase. These are not one slice:

- **Org tenancy** is a refactor of every `owner_github_id` filter (8 in `jobs.py`
  alone), every model, a data migration, and the runner auth path.
- **The policy engine** is additive on top of `Engagement`, `Authorization`, and
  `ScopeItem`, which already exist.

Bundling them means neither lands cleanly. **Phase 1a is the policy engine.**
The justification is that it is the earliest thing that is genuinely broken:
`Authorization` stores `window_start`, `window_end`, and `status`, and grepping
`jobs.py`, `scans.py`, `runner.py`, and `schedules.py` for `Authorization`
returns nothing. The platform records authority and then ignores it — a
default-allow on a product whose entire premise is authorized testing.

Org tenancy is **Phase 1b**, sequenced second because it is a larger refactor of
working code, not because it matters less.

---

## Phase 0 — Discovery and hardening ✅ this PR

- [x] Repository audit; languages, frameworks, deployment, design system
- [x] Baseline recorded (above)
- [x] `product-vision.md`, `architecture.md`, `domain-model.md`,
      `security-model.md`, `implementation-roadmap.md`
- [x] Threat model with control status
- [x] Critical defect identified and fixed: authorization never enforced (T1)
- [x] Migration and compatibility strategy documented

## Phase 1a — Engagement policy engine ✅ (advisory since v0.29.0)

- [x] `backend/policy.py` — pure, DB-free, typed `PolicyDecision` + reason codes
- [x] Scope matching: domain, subdomain wildcard, IP, CIDR, URL, API route
- [x] Exclusions beat inclusions; ambiguity warns
- [x] Stop-work switch on the engagement — the one finding that still refuses
- [x] Authorization status + window evaluation
- [x] Evaluated at **job creation, job claim, and PATCH → `running`**
- [x] Migration `0016` — reversible
- [x] Tests for every reason code, all three evaluation points, bounty carve-out
- [x] **v0.29.0:** findings returned as `warnings` rather than enforced; scope is
      the operator's responsibility (ADR 0001 § Amendment). Warnings are not audited.

## Phase 1b — Organizations and RBAC ✅

- [x] `organizations` + `organization_members` with ordered roles
- [x] `org_id` on `Client` and `Engagement`; access resolves through
      `deps.engagement_access()` (ownership ∪ org membership ∪ invitation)
- [x] All 11 `owner_github_id == current_user` filters in `routers/jobs.py`
      replaced by `accessible_engagement_ids()`
- [x] Tenant-isolation tests both directions (16)
- [x] Backfill: one personal org per existing owner, reversible
- [ ] Runner API keys scoped to org rather than user
- [ ] Drop `owner_github_id` once no code path reads it (separate change)
- [ ] `teams` as a sub-grouping within an org

## Phase 2 — Operational workflow

- [x] **Asset graph** — `assets` + `asset_relationships` edge table, canonical
      identity normalization, `asset_id` FK on recon/scan/service/finding,
      backfill with documented merge-collision handling (v0.26.0)
- [ ] Objectives, TestPlan, TestCase mapped to WSTG / API Top 10 / ATT&CK
- [ ] Observation as a first-class entity
- [x] Evidence with content hash, provenance, sensitivity, retention (v0.27.0)
- [x] Centralized redaction (auth headers, cookies, tokens, URL credentials) (v0.27.0)
- [x] **dnsx + naabu queueable** — VardrRunner already had handlers; VardrMap's
      `_VALID_TOOLS` did not accept them. Two named pipelines ship with them
      (v0.30.0)
- [ ] Finding lifecycle migration + Retest entity

### VardrGate integration ✅ (v0.31.0 – v0.32.0)

`vardrgate_api_test` has a complete handler in VardrRunner (`REGISTRY`) and is
the most differentiated job type in the product family. It is now queueable
end to end, with **no VardrRunner change required**.

- [x] **1. `authorization_test_cases` + CRUD** (v0.31.0) — engagement-scoped
      storage for VardrGate specs, referenced by jobs rather than copied into
      them. Credential values are rejected on write: identities must use
      `value_env` / `value_keychain` so the secret resolves on the runner and
      never reaches the database. Migration `0021`.
- [x] **2. Spec inlined in `GET /jobs/pending`** (v0.32.0) — `_resolve_test_cases`
      expands `config.test_case_id` into `config.test_case` on the response only.
      `ScanJob.config` stays flat for validation while
      `VardrGateConfig.from_dict` receives exactly the object it expects. A job
      whose case was deleted is auto-failed rather than left pending.
- [x] **3. `POST /jobs/{id}/upload`** (v0.32.0) — `findings[]` → `ScanItem`
      (`source="vardrgate"`, `template_id` = the VardrGate case id) so the
      existing triage and promote-to-finding flow applies, and `executions[]` →
      `Evidence` with content hashing. Redacted on write regardless of what the
      sender omits.
- [x] **4. `vardrgate_api_test` in `_VALID_TOOLS`** (v0.32.0) — config is
      `{test_case_id, timeout}`, validated at queue time and scoped to the
      engagement so a case cannot be borrowed from another one.
- [x] **5. API Assessment pipeline** (v0.32.0) — `httpx → vardrgate_api_test`,
      with a test-case picker in the Composer and Queue disabled until a case is
      chosen.
- [x] **6. Result and contract hardening** (v0.34.1) — uploads are idempotent,
      result provenance is checked against the queued case, and stored cases
      mirror the engine's execution-critical validation before they reach a
      runner.

**Not yet built.** Authoring is still "store the JSON VardrGate produced".
VardrGate's `discover` command and `internal/scaffold` generate cases from an
OpenAPI spec or a Postman collection, so wiring `discover` in as its own job
type — turning a spec upload into a set of stored cases — is the natural next
iteration.

**Validated against the Go structs, not a live run.** The result mapping was
built by reading `engine.Result` and `model.Finding` in the VardrGate repo. The
shape should be confirmed against one real VardrGate invocation; `severity` is
the field most worth checking, since an unrecognised value deliberately falls
back to `info` rather than being guessed upward.

### Burp-assisted API Surface ✅ (v0.34.0 – v0.34.1)

Selected Burp exchanges can be promoted into a canonical API operation
inventory without synchronizing Proxy history. VardrMap retains doubly-redacted
request/response evidence and visualizes status and identity coverage. v0.34.1
adds operation/exchange pagination, concurrent-safe operation ingestion,
multi-selection, source-tool provenance, and response content type capture.

## Phase 3 — Private execution

- [ ] Versioned job envelope derived from VardrGate `internal/job.Envelope`
- [ ] Runner registration, capabilities, health
- [ ] Signed, immutable jobs; policy re-evaluated runner-side
- [ ] Cancellation and emergency stop propagation
- [ ] VardrGate adapter behind the contract

## Phase 4 — Red team and reporting

- [ ] Campaigns, attack-path hypotheses, ATT&CK plans
- [ ] Detection outcomes and time-to-detect
- [ ] Engagement-level report generation (currently per-finding only)

## Phase 5 — Continuous assurance

- [ ] Scheduled retests, CI integration, regression tests from findings
- [ ] Notifications, ticketing, coverage and trend analysis

---

## Migration and compatibility strategy

**Additive first.** Every migration in Phases 0–2 adds columns or tables. No
column is dropped or renamed while a running process still serves the old shape
— `start.sh` runs `alembic upgrade head` *then* starts uvicorn, so there is a
window where schema has moved and the old process is still live.

**Reversibility.** Every migration implements `downgrade()`. Destructive
migrations state the data loss in the docstring and require explicit sign-off
(`CLAUDE.md` hard rule).

**Single head.** `alembic heads` must return exactly one line. Two branches
naming the same `down_revision` is a failed deploy, not a merge conflict.

**API compatibility.** `LegacyProgramPathMiddleware` rewrites `/programs/*` to
`/engagements/*`. VardrRunner already calls `/engagements/*`, so the alias can
retire once the `programs` response key is dropped — tracked in `roadmap.md`.

**Default-deny rollout risk — resolved in v0.29.0.** Phase 1a changed job
dispatch from allow to deny, which meant `pentest`/`red_team`/`internal`
engagements needed an authorization record before anything would run. v0.29.0
makes those findings advisory, so no engagement is blocked by a missing record;
the warning tells the operator what is absent and the job proceeds. Stop-work is
the only remaining refusal.
