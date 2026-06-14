# Roadmap

Forward-looking backlog. Shipped history lives in [`CHANGELOG.md`](../CHANGELOG.md);
the canonical session rules and "shipped" list live in [`CLAUDE.md`](../CLAUDE.md).

Until GitHub issues/milestones are adopted, this file is the backlog of record.
When an item ships it moves to the changelog and its `changelog/vX.Y.Z.md` notes.

---

## v0.20 (next) — candidate milestone

A small, trackable milestone. Not everything here must ship together — pull the
highest-value items first.

### Validate v0.19 in production

v0.19.0 shipped RBAC, API key scopes, recon dedup, and webhooks; v0.19.1 cleared
the dependency audit. These need a production smoke pass on Railway + Vercel:

- [ ] Confirm migration `0011rbacreconscopes` applied cleanly — `alembic current`
      equals head, `program_members` table and the new `recon_items` /
      `api_keys` columns exist.
- [ ] **RBAC:** invite a second GitHub account to a program; verify the member
      can read/write program resources and that a non-member still gets `404`
      (not `403`) — the BOLA invariant.
- [ ] **Runner-scoped keys:** a `runner`-scope key succeeds on jobs / imports /
      heartbeat and is blocked (`403`) everywhere else; a browser JWT stays
      full-scope.
- [ ] **Recon dedup + alerts:** re-import the same httpx scan → `new_count == 0`
      and no duplicate rows; importing a genuinely new asset fires the webhook
      (when configured) and respects `notify_min_severity`.

### Platform / ops

- [ ] **Migrate the production runtime off Node 20.** Node 20 reaches
      maintenance EOL in 2026; v0.19.1 added a Node 24 CI leg to de-risk this.
      Once 24 has been green in CI across a few runs, bump `.nvmrc` 20 → 24
      (Vercel reads it) and verify a Vercel **preview** deploy before promoting
      to production.
- [ ] **Automate dependency freshness.** Add Dependabot (or Renovate) for
      `frontend/` and `backend/` so security bumps like v0.19.1 are
      opened as PRs proactively rather than discovered when CI's audit gate
      fails. Group patch/minor updates to keep noise down.
- [ ] **Track the `glob@7` deprecation warning.** Surfaced on `npm ci`;
      transitive (via an ESLint/Jest dependency) and not a vulnerability.
      Re-evaluate once the upstream tool updates its `glob` dependency.

### Product

- [ ] **RBAC depth** — roles beyond owner/member (e.g. a read-only viewer);
      record membership changes in the audit log.
- [x] **VardrRunner repo extraction** — `runner/` split into its own repository,
      [jorge-aquino/VardrRunner](https://github.com/jorge-aquino/VardrRunner), with full
      history; removed from this repo. Integrates over the HTTP API only.

---

## Conventions

- Patch releases (`vX.Y.Z`) = fixes, security bumps, CI/doc maintenance.
- Minor releases (`vX.Y.0`) = new endpoints, models, env vars, or user-visible
  features. Every behavior-changing item updates `docs/` per the rules in
  `CLAUDE.md`.
