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

### VardrGate integration — blocked, not forgotten

`vardrgate_api_test` has a complete handler in VardrRunner (`REGISTRY`) and is
the most differentiated job type in the product family. It is **not** in
`_VALID_TOOLS` because two pieces are missing on this side:

1. **`POST /jobs/{id}/upload`** — the handler posts its sanitized result there
   and the endpoint does not exist. Needs a decision on where a VardrGate result
   lands: job artifact, `Evidence` rows, or promoted `Finding` rows.
2. **A `test_case` model** — `VardrGateConfig` requires a structured object
   (request spec, identities, credential references resolved locally by the
   runner). VardrMap has no model, storage, or authoring UI for it, and
   `_TOOL_CONFIG_KEYS` only permits flat scalar keys.

Until both land, adding the tool would let an operator queue a job that fails at
config parse — or, past that, executes and then 404s on upload. Pinned by
`test_vardrgate_is_not_queueable_yet`.

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
