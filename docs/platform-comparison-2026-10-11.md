# VardrSec and ars0n: workflow comparison

Reviewed 2026-10-11. This is an engineering/workflow comparison, not a security
certification or a finding-rate benchmark. Vardr's controlled fixtures were run;
ars0n was inspected without launching its scanners against external targets.

The first sections preserve the pre-feature baseline. The final update records
the implementation and verification of assessment, provenance and shared guidance.

## Sources and revisions (baseline)

- VardrMap: `codex/postgres-reliability`, based on `49e786`, including PR #85.
- VardrRunner: local `77a56c8dd93de184ec26bf39e7a6658e5bfbfecc`.
- VardrGate: local `f756df11d366948e8e8de6846e5b91a3b5873ac2`.
- VardrSec website: local `56d943b3c4e7c27beb0f99b7d23cd5b090ae9a3f`.
- ars0n: local `0b251995feaa20e1ad017f377e95fc789c76496b`, plus the fetched
  [current upstream revision](https://github.com/R-s0n/ars0n-framework-v2/tree/8b3c20561f50998316f98d9c8a1a9ad7d080495f).
  The upstream update adds deterministic hunt completion and session-keeper work.
  Its working tree was not changed. README claims were checked against code.

The Vardr checks below use supplied local checkouts. CI deliberately uses the
companion commits in `.github/workflows/ci.yml`; those revisions are a separate
reproducible compatibility baseline, not an assertion that every local branch
has been merged or released.

## What each lineup is good at

| Area | VardrSec implementation | ars0n implementation | Assessment |
| --- | --- | --- | --- |
| Engagement delivery | Map has clients, written authorizations, engagement membership, evidence, finding activity/retests and immutable client report revisions. | Company/wildcard/URL workflows, target research and hunting goals are central. | Vardr is the closer fit for delivering a contracted API assessment. That is a product-fit judgment, not a claim that ars0n cannot be used in a pentest. |
| Guiding the operator | Runner has five MCP prompts and versioned OWASP/WSTG planning checklists. Map exposes a case builder and job/pipeline composer. | 37 attack playbooks, XSS/SQLi workflow books, session refresh playbooks, tool guidance and data-driven `whats_next`. | ars0n currently explains the testing process more thoroughly. Vardr should improve guidance before adding lots of tools. |
| Declared API authorization | Gate replays reviewed requests across identities with explicit ownership, tenant and role context. It supports declared status/body denial conventions and local credential references. | Access-bypass/vector workflows and broad web testing guidance exist. | Gate is a distinct strength for repeatable checks against intended access. No comparative detection benchmark was run. |
| Discovery and attack breadth | Runner orchestrates a smaller registered tool set, including ffuf/dalfox, plus Gate. | Code includes content/parameter discovery, an attack-vector model and several scanner families. | ars0n has broader web hunting workflows. Chasing tool count would dilute Vardr's API strength. |
| Browser capture and session maintenance | Map's Burp extension captures selected exchanges. Runner resolves secret references locally; a complete application login/refresh recorder is not present in the inspected lineup. | Browser capture, auth sessions, refresh guidance and session-keeper code are integrated. | Authentication setup and stale-session handling are a substantial Vardr usability gap. |
| Explaining incomplete work | Gate records ambiguous outcomes; Runner methodology prompts avoid coverage percentages. Gate's OpenAPI coverage utility matches case definitions to operations. | Current upstream computes hunt axes from run tables and blocks premature automated-goal exhaustion when required axes are missing/unknown. | Vardr needs an execution-backed assessment view. A defined case, completed command and verified control are three different facts. Neither product's completion count proves exhaustive security coverage. |
| Installation and operation | Separate Map, Runner and Gate deployments; Runner has verified installs, doctor, host services and durable execution journal. | Docker Compose assembles the framework and its companion services. | Vardr offers useful operator-machine control, but three repositories make first-time setup harder. A single guided API engagement is more valuable than another dashboard. |

Source paths checked include ars0n's
[`attackplaybook.js`](https://github.com/R-s0n/ars0n-framework-v2/blob/8b3c20561f50998316f98d9c8a1a9ad7d080495f/docker/mcp-server/src/tools/attackplaybook.js),
[`workflow registry`](https://github.com/R-s0n/ars0n-framework-v2/blob/8b3c20561f50998316f98d9c8a1a9ad7d080495f/docker/mcp-server/src/workflows/index.js),
[`methodology tools`](https://github.com/R-s0n/ars0n-framework-v2/blob/8b3c20561f50998316f98d9c8a1a9ad7d080495f/docker/mcp-server/src/tools/methodology.js), and
[`hunt completion calculation`](https://github.com/R-s0n/ars0n-framework-v2/blob/8b3c20561f50998316f98d9c8a1a9ad7d080495f/server/utils/huntCoverage.go).
Vardr sources include Map's resource routers, API Surface/case/report UI, Runner's
handler registry/MCP prompts and Gate's engine, discovery and coverage packages.

## Measured gaps and limits

The expanded Map → Runner → Gate acceptance run passed 82 checks on both SQLite
and a fresh migrated PostgreSQL database using TLS. The API fixture received 70
loopback requests, under a 100-request ceiling. Browser acceptance passed four
journeys against a fresh real SQLite backend: login presentation, pentest creation
through candidate promotion/report download, viewer access/revocation and expired
backend identity. The session response is stubbed only inside the browser;
application API requests use real backend authentication and persistence.

The 429, 503 and redirect fixtures all return zero authorization findings and
retain their ambiguous outcomes in uploaded evidence. Runner marks those jobs
`done` because the process executed. That is not a clean assessment, and the
handler's `0 finding(s)` summary does not explain the distinction. The acceptance
run records this behavior rather than relabeling the result as verified.

Gate's `internal/coverage.Analyze` matches methods/paths in case definitions; it
does not consult execution outcomes. Its `tested` terminology should not be used
as evidence that those operations ran successfully. A future Map view should
separate inventoried operations, reviewed cases, executed identities, conclusive
decisions and reviewed findings.

Map preserves uploaded Gate execution evidence, but these evidence rows do not
carry a first-class job/case/identity relation: the upload builds text and attaches
it to the engagement. The new fixture identifies new evidence by before/after IDs.
Adding durable references would make playbook progress and report provenance much
easier to derive without parsing body text or guessing from timestamps.

The injection canary check proves parameter transport integrity only. Gate is an
authorization engine; no new SQL injection detection capability was implemented
or benchmarked. Pagination tests replay two deliberately reviewed pages; they do
not prove automatic traversal of every page in an unknown API.

No hosted Railway/Vercel, real GitHub OAuth, automatic session refresh, production
data migration or destructive scanner behavior was exercised. The website was
checked for lineup framing: it already leads with API authorization, while its
experimental VardrScanner listing should be reconciled with Gate's role before
adding another API product. Runner's README tool bullets also omit ffuf/dalfox
although its registry includes them; update that repo's overview when releasing.

## Playbooks are worth adding

Yes. Their value is reducing the decisions an operator must reconstruct between
screens and tools. Start with API authorization and capture-to-retest, where the
lineup already has executable primitives. Original starter runbooks are in
[API playbooks](api-playbooks.md); they are documentation, not newly registered
MCP tools or an automated execution engine.

Use one versioned definition per playbook, shared by UI and MCP. Each definition
should identify prerequisites, needed identities/objects, the operation and
expected decisions, manual review points, expected artifacts, common inconclusive
outcomes, retest steps and exclusions. Retrieve an index first and one playbook
or section on demand so guidance does not consume tokens on every tool call.

Derive live progress from persisted job/evidence/activity records. Do not add a
second mutable checklist that gets a tick because a scanner ran. Do not guess
allow/deny decisions, treat scanner matches as confirmed issues, or expand scope
as a side effect of guidance. Keep target-controlled content in tool results,
following Runner's existing prompt trust boundary. Stop-work remains the
operator's halt; authorization/scope warnings remain advisory.

Borrow the design idea, not ars0n's prose or payload catalog. The starter content
here is original and grounded in Vardr's current contracts.

## Priority order (baseline)

1. **Execution outcome and provenance.** Show inconclusive/partial results next
   to completion; persist job/case/identity references for Gate evidence. Add
   negative fixtures to prevent a future UI from calling ambiguous results clean.
2. **A guided API engagement.** Put the three starter playbooks in the case
   builder and MCP as read-only guidance, sharing one source. The acceptance
   criterion is getting from captured traffic to reviewed cases, evidence and a
   retest without undocumented context.
3. **Identity setup and session preflight.** Verify the legitimate baseline and
   distinguish expired credentials from authorization behavior. Add refresh
   support deliberately, with secrets remaining on the operator's machine.
4. **Sustained assurance.** Run reviewed Gate policies after application changes,
   compare findings to a baseline, and explain missing identities/pages/cases.
   Add hosted staging/OAuth only after dedicated staging resources exist.
5. **Selective broader testing.** Add an API vulnerability class only with an
   explicit detector, safe fixture and evidence contract. Preserve manual
   business-logic review; do not advertise all-OWASP coverage from scanners.

Revisit this comparison when companion pins or workflow behavior change. For
each proposed feature, require a user problem, an executable fixture or manual
acceptance criterion, and a clear statement of what the evidence cannot prove.

## Platform update: assessment, provenance and playbook integration

The comparison above records the pre-feature baseline. In the current feature
branches, Map has an assessment summary separate from lifecycle, claim-time case
snapshots and structured job/case/identity evidence. Results carry an unresolved
case hash from Runner; unbound historical/legacy results stay unknown/inconclusive.
The UI can inspect a run and link its exact evidence to a reviewed finding; new
report revisions and activity entries retain that provenance.

The three original API playbooks are now one backend versioned catalog, read on
demand in the case builder and through Runner MCP. MCP has a sixth instruction-only
prompt, api_playbook, and read tools for the catalog and filtered evidence. This
closes the initial integration gap without copying ars0n's playbook prose. ars0n
still has much broader web-testing guidance (37 attack playbooks at the inspected
revision), session maintenance and hunting workflows. This does not establish
comparative detection performance or exhaustive API coverage.

The next substantive gap is identity/session preflight and refresh. Invalid or
missing legitimate baselines are now visible; verifying a separate known-good
login/session endpoint and refreshing credentials remain future work. Hosted
OAuth/deployment checks still need dedicated staging resources. Review this
comparison on platform updates, as requested, rather than on a weekly schedule.

Final validation of the update: 1061 backend tests on both SQLite and PostgreSQL
(1 platform skip), 144 frontend tests, five browser journeys, and 89 real
Map → Runner → Gate checks on each database backend (70 loopback requests each,
under the fixture ceiling). Runner passes 1429 tests (10 opt-in smoke tests
skipped) at 95.80% coverage. PostgreSQL migration checks include the additive
0027 round trip and retention; frontend lint/typecheck/build and Runner ruff/mypy
pass. Local acceptance uses Runner 923cb08 and Gate f756df1; CI pins Runner 923cb08
and the equivalent merged Gate baseline bb242589. These are tested feature
branches, not a statement that deployment or release occurred.
