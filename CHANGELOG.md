# Changelog

All notable changes to VardrMap. Full release notes live in [`changelog/`](changelog/).

## Unreleased

- Trial a nonce-based **report-only** script CSP for HTML navigation in the
  existing Auth.js proxy. The currently enforced page CSP stays unchanged.
  HTML becomes dynamic, and nonce-bearing responses are private/no-store.
  Browser acceptance verifies framework script nonces, fresh nonces across
  requests and the existing sign-in path. Enforcement requires separate review
  of observed Chrome/Firefox violations and performance impact.

- Send security headers with every web page and asset, in Compose and on Vercel:
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`,
  `Permissions-Policy` and `Content-Security-Policy: frame-ancestors 'none'; base-uri 'self';
  object-src 'none'`. Only API responses carried them before. None of these restrict scripts,
  styles or connections, so rendering and sign-in redirects are unchanged; a script-source
  policy is not set yet. The browser acceptance test checks the page headers.

- **Behaviour change:** `DELETE /jobs/{id}` requires a browser session or a full-scope API key. A
  runner-scoped key could delete job records; VardrRunner never does, so it now receives `403`.
  A new route inventory test reads every route from the app and checks that runner keys reach only
  the listed runner routes, that a user without access gets `404` on engagement and job reads (and
  no success anywhere on them), and that engagement and job writes apply a write guard. The API
  reference test now sees routes registered through included routers too; `GET
  /engagements/{program_id}/scope` is documented and the playbook paths use `{program_id}`.

- **Behaviour change:** `PATCH /jobs/{id}` enforces job state transitions. A job enters `running`
  only through `POST /jobs/{id}/claim`, which evaluates policy and freezes the case snapshot; a
  `done` or `failed` job never reopens. Allowed: `pending` → `failed`/`done`, `running` →
  `done`/`failed`/`pending` (stop-work release). Anything else returns `409` and changes
  nothing; repeating the current status is a no-op. VardrRunner, the job board's cancel and
  its re-queue already use only these transitions.

- Reject `${...}` environment references anywhere in a stored authorization test case. VardrGate
  expands them from the environment of the process that runs it, so a stored reference could read
  any variable on the runner and send it to the case's target. Credentials keep using `value_env` /
  `value_keychain`; setup captures (`{{name}}`) are unaffected. Existing stored cases are not rewritten.

- Reconcile setup, architecture and API guides with the existing Compose/local-account
  path, provider-conditional GitHub credentials and shared session authorization.

- Fix boundary drafts to compare callers with the resource's tenant, matching relationship classification,
  rather than always using the owner's tenant. Conflicting resource-tenant declarations are reported as
  missing context and never resolved by case order. Draft decisions remain `skip`; nothing is saved or queued.

- Make boundary questions actionable and fix relationship integrity. A question's **Draft authorization test**
  opens the existing case builder for that operation with the identities, credential references (never values),
  tenant/role and resource owner that are unambiguous in reviewed cases, lists what is still missing, and keeps
  every expected access at `skip` (new `boundary` option on the existing preview endpoint; nothing is stored or
  queued). Relationship analysis no longer takes an identity's first declaration: contradictory tenant, role or
  credential declarations are reported in `identity_conflicts` and excluded, cases are classified only from their
  own declarations, and an `identity_ids` draft refuses contradictory identities.

- Add Authorization Relationship Intelligence: a read-only `GET /engagements/{id}/api/relationships` and a
  Boundary questions panel. From the tenants, roles and resource owners declared in reviewed cases it
  classifies callers (different tenant, same-tenant peer, higher role than the owner, no credentials) and lists
  the boundaries on each worth-testing operation that have no current, evaluated result, with the facts that
  make each question askable. It infers nothing from traffic, never assumes an undeclared tenant or role, treats
  an edited case's earlier run as history, and presents hypotheses, not findings. No migration or new table.

- Fix authorization coverage attribution. A case edited after it ran no longer inherits the old run's
  coverage: a run is current only if its claim-time snapshot hashes to the case's present spec and was
  verified; otherwise it is kept as `historical_assessments` (case modified, case deleted or snapshot
  unverified), attributed to the operation it actually exercised, and its candidates stay flagged there.
  A reviewed case whose only runs predate its definition shows the new `stale` state. An identity
  evaluated by some matching cases but not others is `mixed`, not `evaluated`. No migration, and no
  assessment, finding or evidence is changed or removed.

- Let a researcher go from an authorization-coverage violation candidate to the proof behind it:
  operations now carry `candidate_evidence` references (job, case, identity, reviewed and observed
  decision, content hash), and the panel loads the redacted record through the existing evidence
  endpoint on request, showing whether its hash matches the reference. Nothing new is stored.

- Add `priority_reasons` and `sort=priority` to authorization coverage. Each operation lists the stored
  facts that make its boundary worth testing (object identifier in the route, state-changing method,
  boundary-style request fields, 2xx captured for several identities or without credentials), and the
  panel can order operations least-tested first. Reasons come only from captured records, are
  explained rather than scored, and never remove an operation from the list.

- Let a case draft reuse the engagement's existing identities: `POST /engagements/{id}/test-cases/preview`
  accepts optional `identity_ids` and copies only each identity's id and credential reference from
  the engagement's stored cases (never a value, a preflight or another engagement's identity;
  unknown ids are refused). Every expected access stays `skip` until a person decides. The
  authorization coverage panel gains a "Draft test" action on operations with identities that
  have not been evaluated, which selects the operation and those identities in the case builder.
  Omitting `identity_ids` keeps the generic anonymous/member template.

- Add authorization coverage to the API Surface: a read-only `GET /engagements/{id}/api/coverage`
  and a panel that join observed operations, reviewed cases, executed Gate assessments,
  candidates and evidence, so a researcher can see which operations are untested, reviewed but
  not run, partially or inconclusively assessed, conclusive, or carrying a violation candidate,
  and which identities were never reviewed against each. It invents no expectation, treats a
  completed job without an assessment as not executed, and never reads `conclusive` as secure.
  No migration, new table or new execution path.

- Add an Overview "Client & testing window" and "Written authorization" panel so a
  researcher can create/link a client, set the testing window and record a written
  authorization from the interface. These were previously API-only. Viewers do not
  see the panel; no backend endpoint, field or migration changes, and scope and
  authorization remain advisory. The browser acceptance suite now records scope
  and authorization through the UI.

- Pin backend Python and frontend Node container bases to reviewed Debian Trixie
  digests. Remove npm/npx from the web runtime stage; the build stage retains npm
  and its existing lint, type, test and build checks. These image changes address
  reported base/package-manager findings and still require image rescanning and
  installed acceptance before alpha release; native setup is unchanged.

- Accept Runner's existing `policy_warning` lifecycle events so advisory policy
  messages persist in the job history instead of returning 422. Existing event
  access checks and job/stop-work behavior are unchanged; no migration is required.

- Enforce a hard eight-second status refresh deadline across authentication and
  response reads, even if the request ignores abort; ignore late success after timeout.

- Add Settings platform/Runner observations with readiness, timestamps, reported
  versions/tools and explicit stale, unknown and unreachable states. Expire cached
  Jobs bridge contact and clear it after failed refreshes. Heartbeat status gains
  additive freshness metadata and UTC timestamps; no migration or worker is added.
  See [status behavior](docs/platform-status.md).

- Add non-root backend/frontend development Dockerfiles, allowlisted build
  contexts and image CI. Preserve migrated backend startup; require an explicit
  public API build URL. See [container setup](docs/containers.md).

- Add public, value-free `GET /ready` database/Alembic-marker readiness for Runner
  installation diagnostics. Keep `/health` liveness unchanged; probes preserve
  TLS policy, do not apply migrations and return 503 on uncertainty. No migration
  or frontend change is required. See ADR 0003 and the API reference.

- Remember the selected browser login method per tab/API and fail closed on
  provider errors or expiration instead of silently switching identities. Add
  sign-in recovery guidance, mixed-session coverage and a trusted local HTTPS
  distribution release gate.

- Add configured local/GitHub browser login, cookie and CSRF transport through the
  shared request helper, Settings password rotation and server-revoking logout.
  Verify the local flow against disposable HTTPS in browser acceptance.

- Return unauthorized when session revocation races with its activity refresh;
  verify credential lockout and password/recovery races on migrated PostgreSQL.

- Add explicitly configured local authentication alongside GitHub OAuth: one-time
  terminal bootstrap, Argon2id passwords, persisted account/IP throttling,
  revocable secure HTTP-only cookie sessions and Origin/session-bound CSRF checks.
  Preserve existing user/tenant ownership and API-key flows. Additive migration
  0031 refuses automatic credential-deleting downgrade. See ADR 0004.

- Preserve cancellation and reset-baseline failure reasons as inconclusive Gate
  assessments. Add an opt-in real-worker semantic evidence contract and explicit
  older-companion compatibility matrix, including the operator-only finding
  promotion boundary. See `scripts/integration/README.md` for rollout validation.

- Retain bound Gate semantic assessments and value-free readback provenance in
  API assessment/evidence reporting. Show raw HTTP, scanner conclusion, credential
  checks and readback separately. Missing/conflicting proof stays inconclusive;
  legacy receipt replays are unchanged and findings still require confirmation.

- Align the frontend ESLint 10 configuration with Next 16.4.3 and apply the
  frontend dependency group. Existing effect diagnostics remain visible as
  scoped warnings during the documented migration; other lint rules stay active.
  Derive scanning scope-filter results directly instead of manual memoization.

- **Agent proposals.** An MCP agent can now propose a scope item, an authorization record, or
  the engagement's request-rate ceiling, but cannot apply one. A proposal is created as
  `pending` and does nothing until a full-access operator approves it in the Scope section,
  which applies the change; the row keeps the agent's stated reason and cited source.
  `agent_proposals` table (migration `0030agentproposals`, additive), `GET/POST
  /engagements/{id}/proposals` and `.../approve|reject`, and a "Proposed changes" panel.
  Creating a proposal needs only member-write (it is inert); approving or rejecting needs a
  full-access key, so a runner-scoped or prompt-injected agent can never apply its own
  proposal. Pairs with VardrRunner's MCP propose tools. Deploy this before that Runner release.

- The architecture diagram's runner example uses `--engagement` and the `/engagements/{id}/...`
  paths. VardrRunner 0.52.0 removed `--program`, and the runner stopped calling `/programs/*`
  long ago. No behavior change.
- Development docs no longer point to `vardrrunner service uninstall`, which VardrRunner
  0.51.0 removed; they link Runner's manual removal steps for a service left by 0.47.0 or
  earlier. The Settings comment notes that `--install-service` no longer exists. No
  behavior change.
- **Settings → Connect Runner** step 1 offers `vardrrunner update` to update an installed
  runner (VardrRunner 0.50.0+, which runs the pipx upgrade and confirms the version), with
  `pipx upgrade vardrrunner` kept as the one-time step for 0.49 and older. README and
  development docs match.
- Make the composer's **tool list collapsible**, collapsed by default and remembered: it shows
  only the chosen tool, so its settings and Request Controls sit right under the pipelines;
  picking from the open list closes it. Pipelines are unchanged and always visible.
- Add **ffuf to the Content Discovery pipeline** (subfinder → httpx → ffuf → katana → gau): it
  fuzzes the live hosts' site roots, and katana then crawls from what it found. It can be
  excluded like any stage. dalfox stays out of every pipeline: it attacks parameters rather
  than discovering anything, so it remains its own decision.
- **Breaking — remove recurring scans.** VardrRunner runs only when invoked (Runner 0.48.0),
  so a schedule never fired on its own. The Composer's recurrence picker, the Recurring Scans
  panel, `/engagements/{id}/schedules` (GET/POST/PATCH/DELETE) and schedule materialization in
  `GET /jobs/pending` are removed. **Migration `0029dropschedules` drops the
  `scheduled_scans` table and permanently deletes every stored schedule**; its downgrade
  recreates the table empty. Stop-work no longer has schedules to pause.
- Remove the Jobs **auto-run** toggle, which only changed a label: nothing ran a job until
  `vardrrunner jobs run`. The board's `vardrrunner jobs run · N` button is no longer disabled
  while the runner shows offline, and copies the command.
- Add **Request Controls** to the job composer: a requests-per-second rate (httpx, nuclei,
  katana, ffuf) and custom headers, one `Name: value` per line (those plus dalfox), validated
  with the API's rules before queueing. They apply to a single job or to every pipeline stage
  that accepts them, show and enforce the engagement's `max_request_rate`, and round-trip
  through saved profiles. ffuf's separate Requests/sec field moved here.
- Show the runner's **version** beside "VardrRunner" in the Execution Link panel and its
  collapsed strip, in smaller text, including the last reported version while offline.
- Docs and comments: describe the heartbeat as sent by `jobs run` and `vardrrunner heartbeat`
  only (no daemon), name Runner 0.48.0 instead of "the release after 0.47.0", and drop
  scheduled-scan and always-on-runner wording.
- Make **secondary text readable** across the app: hints, step titles, labels, inactive tabs
  and Copy buttons move from `#52525b` (~2.6:1 contrast, below WCAG AA) to a shared
  `--color-muted` token, `#a1a1aa` (~7.7:1); their hover brightens to `#e4e4e7`. Off-state
  indicator dots, wires and the focus border stay dim on purpose.
- **Security:** upgrade Next.js 16.4.0 → 16.4.3 (critical: unauthenticated RCE in the Image
  Optimization API with SVG, GHSA-2464-fhr4-w9xw; unauthenticated RCE in `use cache` functions
  returning typed arrays, GHSA-673q-mjm6-r5xr; Server Actions DoS, GHSA-p3m5-59mp-jv5r) and the
  DOMPurify override ^3.4.16 → ^3.4.17 (critical sanitizer bypasses GHSA-cg2g-xh64-v4q7,
  GHSA-mrv2-3pqr-j5jr, GHSA-c6gr-qvv4-5v3f; pulled in by jspdf). `npm audit --omit=dev` is clean.
- Add a **VardrGate install step** to Settings → Connect Runner (now seven steps): one
  copyable command for Windows PowerShell and one for macOS/Linux. Each downloads the pinned
  VardrGate release (v0.1.0), verifies it against the release's `SHA256SUMS` and refuses it on
  a mismatch, then installs it on `PATH` (`%LOCALAPPDATA%\Programs\VardrGate` or
  `~/.local/bin`, no sudo) and prints its version. Marked as needed only for API assessments;
  the manual download link stays.
- Fix **Settings → Connect Runner** for VardrRunner's manual-invocation release (Runner
  PR #60): the connect command is now `vardrrunner init --url <api> --no-install-tools`,
  because Runner now rejects `--install-service` and installs no startup service. Step 5 adds
  `vardrrunner heartbeat` before **Verify connection** (nothing heartbeats in the background
  any more), and step 6 shows `vardrrunner jobs run` for executing queued jobs. The Jobs
  tab's queued/pending messages no longer mention a runner service. README and
  `docs/development.md` match. Works with Runner 0.47.0, which still asks whether to install
  a service (answer no).
- Add bulk scope import: `POST /engagements/{id}/scope/import` parses a HackerOne scope CSV
  and, with `commit: false`, returns a preview (what each row maps to, which rows are already
  present, which were skipped and why) without writing; `commit: true` inserts only the new
  items. Asset types map to scope kinds, `eligible_for_submission: false` rows become
  out-of-scope, and `max_severity` is stored as a per-asset advisory cap. Re-importing an
  updated export only adds what changed. A Scope → "Import from a scope CSV" panel drives it
  with a preview-before-save step. Adds `scope_items.max_severity` (migration 0028).
- Add `rate` and `headers` to scan-job config for the tools that send live traffic (`rate`
  on httpx/nuclei/katana; `headers` on those plus ffuf and dalfox), validated at queue time:
  `rate` 1–1000, and headers with HTTP-token names and no control characters in values so a
  job config cannot inject a header or request line. **Pairs with VardrRunner**, which passes
  them to the tools.
- Add a per-engagement request-rate ceiling, `programs.max_request_rate` (migration 0028,
  nullable). When set, a job's `rate` for httpx/nuclei/katana/ffuf is capped to it — an
  explicit rate above the ceiling is refused, and a job with no rate has the ceiling applied
  (never above the tool's own default) — so a program's rate limit binds. Settable on
  engagement create/update; `null` clears it. Applies to jobs, pipeline stages and schedules
  at creation; changing the ceiling does not retroactively re-cap existing schedules.
- Rewrite **Settings → Connect Runner** as six plain steps, each command with a Copy
  button: install (or upgrade) VardrRunner, get a runner key (shown once), connect the
  machine with `vardrrunner init --url <api> --install-service --no-install-tools`,
  install or check tools with `vardrrunner tools install --all`, verify the connection
  (with `vardrrunner doctor` if offline), and start on an engagement with `scope` and
  `run httpx --scope`, pre-filled with the open engagement's ID. This fixes the old steps:
  `vardrrunner daemon install` does not exist in current VardrRunner, `daemon start` runs
  in the foreground, and the key appeared on the command line and in a downloadable `.ps1`
  (now removed). The key is never part of a command; `init` prompts for it. The Jobs hints,
  `docs/development.md` and the README match.

- Add reviewed, optional identity/session preflight for Gate cases. Match a
  known-good session response before authorization requests; failed checks stop
  the case, retain bound diagnostics and remain inconclusive. Show session results
  separately in the job panel and explain authoring in the case builder. No
  automatic login/refresh, scope enforcement or schema migration is introduced.
- Expand the real three-product loopback acceptance fixture with session checks.

- Record the proposed remote MCP authorization ADR, updated for current organization
  access, grant-binding/revocation requirements and the traffic caused by queue
  permissions. Documentation only; OAuth implementation and design acceptance remain pending.

- Refresh README, domain/workflow documentation and contributor instructions for
  implemented assessments, execution provenance, shared playbooks and current
  security boundaries; distinguish historical plans from the current backlog.

- Separate Gate assessment completeness from job lifecycle, with per-identity
  evaluated/inconclusive/missing/skipped outcomes and legitimate-baseline checks.
- Bind results to a claim-time case snapshot using a SHA-256 from Runner; legacy
  uploads remain usable evidence with an inconclusive assessment.
- Preserve structured job/case/identity provenance in Gate evidence, finding
  activity and new client report revisions; expose evidence filters and linking
  in the job UI. Additive migration 0027 leaves historical provenance unknown.
- Serve three original versioned API playbooks from one backend catalog to the
  case builder and Runner MCP. Reading guidance records no coverage or progress.
- Run CI for stacked PRs as well as PRs targeting main.

- Add real browser acceptance against a disposable backend and run it in CI;
  expand Map → Runner → Gate fixtures for denial conventions, stale sessions,
  pagination, parameter integrity and inconclusive HTTP outcomes.
- Add original starter API playbooks, with priorities for guidance, assessment
  outcomes and provenance.

- Preserve Unix virtualenv interpreter paths in the integration launcher instead
  of resolving them to the base Python, and report redacted worker startup errors.


- Preserve ampersands and literal entity syntax in newly sanitized text, keeping
  the existing HTML-removal and identifier rejection rules. Existing stored rows
  are not rewritten; historical recon auditing keeps its frozen transformation.
- Order ORM observation-link deletions before target deletions, removing duplicate
  PostgreSQL cascade deletes without suppressing warnings or adding a migration.
- Use the declared HTTP client
  in the integration harness so clean CI environments need no undeclared requests dependency.


- Require expiry and identity claims in backend JWTs; deny shared client writes by organization viewers.
- Pin webhook connections to validated public IPs while preserving TLS identity;
  reject malformed URLs and avoid logging webhook secrets.
- Bound import reads before size rejection; redact AI inputs and hide provider exception details.
- Reconcile frontend request flow, tenancy, domain model and roadmap documentation with implemented features.
- Update compatible frontend transitive packages, removing the critical Handlebars
  advisory; pin urllib3 2.8.0 to protect Sentry's transitive HTTP dependency.

- Fresh PostgreSQL installs now create the frozen historical baseline before
  applying incremental migrations. Already-versioned databases keep their normal
  upgrade path; nonempty unstamped databases require explicit schema inspection.
- PostgreSQL application and migration connections use UTC, preventing date
  shifts and false offline runner status on databases with non-UTC defaults.
  TLS remains required unless `sslmode` is explicitly supplied in the URL.
- Add PostgreSQL migration, backend and three-product integration checks to CI;
  make the read-only audit assertion portable across SQLite and PostgreSQL.
- Accept legacy VardrGate `findings: null` as an empty list; other malformed
  shapes remain errors. Validate Gate job timeouts at queue time.
- Persist runner `target_stats`, `target_warning`, and `blocked` events.
- Add an explicit evidence-to-finding link endpoint with member-write checks,
  an audit entry, and unchanged evidence identity, content and provenance.
  Existing links cannot be moved to a different finding. No migration.

| Version | Date | Summary |
|---|---|---|
| [v0.43.0](changelog/v0.43.0.md) | 2026-10-10 | **Bug fix** - new recon and nuclei imports store URLs exactly as reported. The importers ran them through `strip_html`, which encoded `&` (`?a=1&b=2` became `?a=1&amp;b=2`); recon URLs are read back as scan targets, so runners scanned a URL whose second parameter was named `amp;b`. Existing rows are **not** rewritten (a blind decode is a guess: five originals collapsed to one value); a read-only audit and a recovery plan are provided for review. No migration |
| [v0.42.0](changelog/v0.42.0.md) | 2026-10-10 | **Behaviour change** - stop-work now pauses a stopped engagement's schedules: they are skipped and left untouched, so release fires one catch-up job instead of a backlog (previously one job per interval queued behind the refused claim and all became claimable on release). No migration |
| [v0.41.0](changelog/v0.41.0.md) | 2026-10-09 | **dalfox** queueable, with its verification signal preserved — tier in `type`, plus new `detection_method` and `confidence` columns, never folded into severity. Imports land as **candidates** (`status: "new"`); no tier maps to confirmed. dalfox imports are deduplicated on the query-less URL + context/parameter + tier, excluding the per-run payload marker. Fix: `/scans?job_id=` now includes observed rows, matching `/recon` and `/services`, so a deduplicated re-scan no longer looks empty. Pairs with VardrRunner v0.46.0. Migration 0026 (additive) |
| [v0.40.0](changelog/v0.40.0.md) | 2026-10-09 | **ffuf** is a queueable job type and Composer tool (its output was already importable). `config.wordlist` is a wordlist *name*, never a path — a path would let a job name any file the runner can read for ffuf to replay at a target; `config.rate` is a load cap with a ceiling and no "unlimited" value. Accepted config *types* mirror VardrRunner's exactly, so a job cannot clear queue validation and then fail locally. Pipelines unchanged. Pairs with VardrRunner v0.43.0. No migration |
| [v0.39.0](changelog/v0.39.0.md) | 2026-10-09 | **Behavior change** - `job_id` on imports/services must be a job of the same engagement. Execution provenance (what each run observed), finding history with remediation and retest tracking, immutable client report revisions, and reviewed VardrGate case authoring; job/event paging and recon `source` filter. Migration 0025 (additive) |
| [v0.38.0](changelog/v0.38.0.md) | 2026-10-08 | "Content Discovery" composer pipeline — subfinder → httpx → katana → gau |
| [v0.37.0](changelog/v0.37.0.md) | 2026-10-08 | **katana** (crawler) and **gau** (archived URLs) as queueable job types and recon imports, with queue-time config validation; composer and import UI entries. Fix: URL recon imports no longer store duplicates from within one upload |
| [v0.36.0](changelog/v0.36.0.md) | 2026-10-07 | **Security** — replace `python-jose` (unpatched critical CVE-2026-85394, HS256 forgery) with `PyJWT` for JWT verification; drop the obsolete `ecdsa` audit ignore. No auth-behaviour or token-format change |
| [v0.35.0](changelog/v0.35.0.md) | 2026-10-07 | Relicensed from MIT to **AGPL-3.0**; README License section; `CONTRIBUTING.md` with a Developer Certificate of Origin sign-off requirement. No code or behavior change |
| [v0.34.1](changelog/v0.34.1.md) | 2026-08-20 | VardrGate result integrity and validation parity; concurrent-safe Burp ingestion; paginated API Surface; richer Burp source metadata |
| [v0.34.0](changelog/v0.34.0.md) | 2026-08-18 | Burp-assisted API Surface — explicit request/response promotion, canonical operation inventory, identity/status visualization, and two-stage secret redaction |
| [v0.33.0](changelog/v0.33.0.md) | 2026-08-17 | **Security** — security headers were absent from CORS preflight responses (middleware ordering); HSTS now production-only. **Breaking** — report statuses become a client-deliverable lifecycle. Pentest-first framing and engagement creation, engagement status panel, constant-query engagement list, corrected API contract drift |
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
