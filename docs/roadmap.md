# Roadmap

Forward-looking backlog. Shipped history lives in [`CHANGELOG.md`](../CHANGELOG.md);
the canonical session rules and "shipped" list live in [`CLAUDE.md`](../CLAUDE.md).

Until GitHub issues/milestones are adopted, this file is the backlog of record.
When an item ships it moves to the changelog and its `changelog/vX.Y.Z.md` notes.

---

## v0.20 — shipped (2026-06-20)

v0.20.0 – v0.20.2 shipped: recon host-detail panel, Dashboard stat cards,
findings search/severity filter, submissions status/platform filter,
finding→submission promotion, Review tab live badges, manual→finding promotion,
scope filter on Recon/Scans, UX hardening (AbortController, debounce, confirm
dialogs, loading skeletons), job-board trash icon, Terminal → Review navigation,
`/programs/{id}/stats` endpoint, N+1 fix, DB indexes, dedup fix, double-commit fix.

See `CHANGELOG.md` and `changelog/v0.20.0.md` – `v0.20.2.md` for details.

### Production smoke checklist (v0.19 → v0.20 upgrade)

- [ ] Confirm migrations `0011rbacreconscopes` and `0012programidindexes` applied
      cleanly — `alembic current` equals head.
- [ ] **RBAC:** invite a second GitHub account; member can read/write resources,
      non-member gets `404` on all program endpoints.
- [ ] **Runner-scoped keys:** `runner`-scope key succeeds on jobs/imports/heartbeat,
      blocked (`403`) everywhere else.
- [ ] **Recon dedup:** re-import same httpx file → `new_count == 0`, no duplicates.

### Platform / ops

- [ ] **Migrate production off Node 20.** Bump `.nvmrc` 20 → 24 (Vercel reads it);
      verify a preview deploy before promoting to production.
- [x] **Dependabot enabled.** Weekly automated PRs for frontend + backend deps;
      security bumps opened proactively.

### Product

- [ ] **RBAC depth** — read-only viewer role; audit-log membership changes.
- [x] **VardrRunner repo extraction** — extracted to
      [jorge-aquino/VardrRunner](https://github.com/jorge-aquino/VardrRunner).

---

## v0.21 — next

- [ ] **Frontend section tests.** `FindingsSection`, `SubmissionsSection`, `JobsSection`
      mutations are untested. Needs `AppContext` + `fetch` mocking harness.
- [ ] **Docs contract test coverage.** `test_docs_contract.py` now catches route and
      enum drift; extend to cover response-key shape assertions as new endpoints are added.
- [ ] **Wire Sentry in production.** `SENTRY_DSN` set on Railway.
- [ ] **RBAC depth** — tracked above.
- [ ] **`react-hooks/set-state-in-effect` rule.** Adopt in ESLint config after
      component-test harness is in place.

## Full-repo assessment notes (2026-06-14, updated 2026-06-22)

Backend: 380 tests, ~97% coverage. The remaining gaps:

- [ ] **Frontend `Section` component tests.** Only `ui.tsx` (15) and the reducer (32)
      are covered. Needs `AppContext` + `fetch` mocking harness.
- [x] **AbortController cleanup.** All fetch effects in FindingsSection,
      SubmissionsSection, ReconSection, DashboardSection now abort on unmount.
- [x] **TypeScript 6 migration.** Build passes. `ts-jest` migration done.
- [ ] **ESLint 10 — upstream-blocked.** Wait for `eslint-config-next` to support it.
- [ ] **Wire Sentry in production.** `SENTRY_DSN` not yet set on Railway.
- [x] **Double-commit fix** (jobs + submissions create).
- [x] **N+1 fix** (serialize_program count queries).
- [x] **Recon dedup host-only fix.**
- [x] **DB indexes** (migration 0012).

Smaller, non-urgent: API-key `last_used_at` writes on every authenticated request
(write amplification at scale); the webhook guard's documented residual
(IPv4-mapped IPv6 / resolve→connect TOCTOU) if this ever goes multi-tenant.

---

## Conventions

- Patch releases (`vX.Y.Z`) = fixes, security bumps, CI/doc maintenance.
- Minor releases (`vX.Y.0`) = new endpoints, models, env vars, or user-visible
  features. Every behavior-changing item updates `docs/` per the rules in
  `CLAUDE.md`.
