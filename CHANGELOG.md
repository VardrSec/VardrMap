# Changelog

All notable changes to VardrMap. Full release notes live in [`changelog/`](changelog/).

| Version | Date | Summary |
|---|---|---|
| [v0.32.0](changelog/v0.32.0.md) | 2026-08-17 | VardrGate authorization testing end to end — spec inlined at hand-off (no VardrRunner change), `POST /jobs/{id}/upload` mapping findings to scan items and executions to evidence, `vardrgate_api_test` queueable, API Assessment pipeline |
| [v0.31.0](changelog/v0.31.0.md) | 2026-08-16 | Authorization test cases — engagement-scoped storage for VardrGate specs, referenced by jobs rather than copied; credential values rejected on write (step 1 of 5 toward queueable `vardrgate_api_test`) |
| [v0.30.0](changelog/v0.30.0.md) | 2026-08-16 | dnsx and naabu queueable (VardrRunner already had handlers); two named pipelines — Attack Surface and Host Enumeration — replace the single recon chain, with per-pipeline stage selection |
| [v0.29.0](changelog/v0.29.0.md) | 2026-08-16 | **Breaking** — scope, window and authorization findings are advisory: jobs return `200` with a `warnings` array instead of `403`, and run. Stop-work still refuses; warnings are no longer audited |
| [v0.28.0](changelog/v0.28.0.md) | 2026-08-15 | **Breaking** — fixes 7 reviewed defects: three scope-matching bypasses, PATCH job-state bypass of the policy engine, viewer job mutation, redaction leaks on spaces/punctuation, unwired asset ingestion, incomplete org tenancy, missing asset FKs |
| [v0.27.0](changelog/v0.27.0.md) | 2026-08-15 | Evidence entity with centralized secret redaction applied on write — headers, body keys, URL credentials, bare JWTs; content hash, sensitivity and retention |
| [v0.26.0](changelog/v0.26.0.md) | 2026-08-12 | Asset graph — canonical identity replaces five free-text host columns; nodes, edges, provenance, backfill, and the "everything about this host" query |
| [v0.25.0](changelog/v0.25.0.md) | 2026-08-12 | Organizations — tenancy moves off the GitHub user id; job/schedule access follows the engagement, so a teammate can finally operate its jobs and share a runner fleet |
| [v0.24.0](changelog/v0.24.0.md) | 2026-08-12 | **Breaking** — central policy engine enforces authorization, testing windows, scope and stop-work at job creation *and* claim; denials audited with stable reason codes; architecture docs and ADR 0001 |
| [v0.23.2](changelog/v0.23.2.md) | 2026-08-09 | Fix crash-looping Railway deploys — wait for Postgres to finish starting before running migrations, instead of burning all 3 restart retries inside the database's recovery window |
| [v0.23.1](changelog/v0.23.1.md) | 2026-08-09 | Fix `NEXTAUTH_URL` in setup docs (v4 name, never read), retarget the AI triage prompt off bug bounty, drop the now-dead `sharp` override, and rewrite `CLAUDE.md` around the pentest model |
| [v0.23.0](changelog/v0.23.0.md) | 2026-08-09 | **Breaking** — Submissions tracker removed entirely (nav, API, model, docs) and migration `0015` drops the `submissions` table; `/stats` no longer returns submission keys |
| [v0.22.1](changelog/v0.22.1.md) | 2026-08-09 | Remove the Recon assets / Findings / Accepted / Paid stat row from the engagement Dashboard — bounty payout framing has no place on a pentest platform |
| [v0.22.0](changelog/v0.22.0.md) | 2026-08-04 | Programs renamed to Engagements (old paths still served); clients, authorization records with testing windows, engagement type/status/dates |
| [v0.21.2](changelog/v0.21.2.md) | 2026-08-08 | Type-check test files in CI (`npm run typecheck`) and fix three fixtures that had drifted from their types since v0.14 |
| [v0.21.1](changelog/v0.21.1.md) | 2026-08-08 | Unblock CI — clear all frontend advisories (next-auth, postcss), replace the now-licensed gitleaks action with the pinned MIT binary, remove both TypeScript 7.0 deprecations |
| [v0.21.0](changelog/v0.21.0.md) | 2026-07-22 | Scan pipelines (subfinder→httpx→nuclei chaining), job→results provenance, AI triage over raw scan output, dry-run target preview, saved scan profiles |
| [v0.20.3](changelog/v0.20.3.md) | 2026-06-23 | Connect Runner panel in Settings — prefilled commands, copy buttons, .ps1 download, Verify connection |
| [v0.20.2](changelog/v0.20.2.md) | 2026-06-20 | Review tab badges, manual→finding promotion, scope filter on recon/scans, UX hardening |
| [v0.20.1](changelog/v0.20.1.md) | 2026-06-20 | Dashboard stats, findings search+severity filter, submissions status+platform filter, finding→submission promotion |
| [v0.20.0](changelog/v0.20.0.md) | 2026-06-20 | Recon host detail panel — services, vulnerabilities, findings joined by host |
| [v0.19.9](changelog/v0.19.9.md) | 2026-06-20 | Submissions: linked finding picker in form, ↗ finding badge in table row |
| [v0.19.8](changelog/v0.19.8.md) | 2026-06-20 | Frontend section tests — FindingsSection (5), SubmissionsSection (5), JobsSection (4); 70 tests total |
| [v0.19.7](changelog/v0.19.7.md) | 2026-06-20 | TypeScript 6 upgrade — fix tsconfig.test.json rootDir + ignoreDeprecations, migrate jest.config globals→transform |
| [v0.19.6](changelog/v0.19.6.md) | 2026-06-20 | Runner-scoped service uploads, settings scope/last-used display, React key fix, docs corrections |
| [v0.19.5](changelog/v0.19.5.md) | 2026-06-13 | VardrRunner extracted to its own repo; `runner/` removed, CI/Dependabot/docs repointed |
| [v0.19.4](changelog/v0.19.4.md) | 2026-06-13 | Backend observability — stdout logging, optional Sentry, webhook failures logged |
| [v0.19.3](changelog/v0.19.3.md) | 2026-06-13 | Webhook SSRF hardening — resolve + block private/metadata addresses at send time |
| [v0.19.2](changelog/v0.19.2.md) | 2026-06-13 | Dependabot — automated weekly dependency + GitHub Actions updates |
| [v0.19.1](changelog/v0.19.1.md) | 2026-06-12 | Frontend dependency security (next 16.2.9, 0 audit vulns), Node 24 CI readiness (matrix + action runtimes) |
| [v0.19.0](changelog/v0.19.0.md) | 2026-06-12 | RBAC program members, recon dedup + new-asset alerts, API key scopes, submissions analytics |
| [v0.18.0](changelog/v0.18.0.md) | 2026-06-12 | Scheduled scans, webhook notifications, multi-runner, Radar → Program tracking |
| [v0.17.1](changelog/v0.17.1.md) | 2026-06-12 | Daemon Windows fixes (status was killing the daemon), Postgres pool pre-ping |
| [v0.17.0](changelog/v0.17.0.md) | 2026-06-12 | VardrRunner daemon — continuous background worker |
| [v0.16.0](changelog/v0.16.0.md) | 2026-06-11 | Submission tracker, delete stuck job, CI hardening |
| [v0.15.0](changelog/v0.15.0.md) | 2026-06-11 | Target Radar, AI triage, service deep-links, rate limits, nmap URL normalization |
| [v0.14.0](changelog/v0.14.0.md) | 2026-06-11 | Service discovery, atomic job claim, config validation, API key tracking |
| [v0.13.2](changelog/v0.13.2.md) | 2026-06-10 | Pin backend Python to 3.12 for Railway deploy |
| [v0.13.1](changelog/v0.13.1.md) | 2026-06-10 | Composer preselect fix, EventCreate validation, docs corrections |
| [v0.13.0](changelog/v0.13.0.md) | 2026-06-10 | Job events table, real Terminal log streaming |
| [v0.12.1](changelog/v0.12.1.md) | 2026-06-10 | Composer preselect fix, error toast detail, Railway config, docs cleanup |
| [v0.12.0](changelog/v0.12.0.md) | 2026-06-10 | VardrRunner real heartbeat, Bridge shows live runner info |
| [v0.11.0](changelog/v0.11.0.md) | 2026-06-09 | Scan Jobs wired to live API, simulation engine removed |
| [v0.10.0](changelog/v0.10.0.md) | 2026-06-09 | Workflow navigation model (7-section sidebar, Dashboard, Review, deep-links) |
| [v0.9.0](changelog/v0.9.0.md) | 2026-06-09 | Scan Jobs orchestration console (Bridge, Telemetry, Composer, Terminal) |
| [v0.8.0](changelog/v0.8.0.md) | 2026-06-09 | PDF export, scan job queue, VardrRunner job commands, subfinder |
| [v0.7.0](changelog/v0.7.0.md) | 2026-06-09 | VardrRunner v1 CLI |
| [v0.6.0](changelog/v0.6.0.md) | 2026-06-09 | Pagination on findings/reports/manual-tests, recon status_code filter |
| [v0.5.0](changelog/v0.5.0.md) | 2026-06-09 | Migration hygiene — Alembic as sole production schema authority |
| [v0.4.0](changelog/v0.4.0.md) | 2026-06-08 | API keys, dual-path auth, Settings section |
| [v0.3.0](changelog/v0.3.0.md) | 2026-06-07 | Scan review workflow, markdown export, inline editing, JWT refresh |
| [v0.2.0](changelog/v0.2.0.md) | 2026-06-05 | Security hardening — sanitization, headers, audit logging, BOLA verification |
| [v0.1.0](changelog/v0.1.0.md) | 2026-06-01 | Initial release |
