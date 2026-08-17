# VardrMap — Security Model

## Threat model

VardrMap holds the authority to attack third-party infrastructure, plus the
evidence of successful attacks against it. The consequences of compromise are
asymmetric: a leaked finding is a disclosed vulnerability in someone else's
production system, and an unauthorized job is an unlawful intrusion attributed
to the operator.

| # | Threat | Control | Status |
|---|---|---|---|
| T1 | Testing outside authorization (expired window, revoked, out of scope) | Central policy evaluator warns; operator decides. Stop-work refuses. | Advisory by design — see below |
| T2 | Cross-tenant read of another user's engagement | `get_engagement_or_404` → 404, never 403 | Implemented |
| T3 | Secrets leaking into findings, evidence, logs, reports | Centralized redaction | Phase 2 |
| T4 | SSRF via webhook or scan target | Resolve-and-block private/metadata ranges | Implemented (webhooks) |
| T5 | Stolen runner API key → arbitrary execution | Runner-scoped keys, hashed at rest, policy re-check at claim | Partial → **this slice** |
| T6 | Audit tampering | No FK constraints; append-only; survives subject deletion | Implemented |
| T7 | Denial of service against a client | Rate/concurrency limits in job envelope | Phase 3 |
| T8 | Prompt injection into AI triage | No raw secrets to model; human approval before intrusive action | Phase 2 |

## Scope is advisory — a deliberate product decision

VardrMap evaluates every job against the engagement's authorization, testing
window, and scope, and **reports what it finds without refusing to run**. Staying
inside scope is the operator's responsibility, the same as it is with every other
tool in the kit — Burp and nmap do not police their users either.

The reasoning: a platform that blocks on its own reading of a scope rule
interrupts legitimate work mid-engagement, and scope in the field is messier than
any rule set (verbal expansions, hosts that appear overnight, ranges that shift).
Being wrong in that direction costs the operator a paid engagement; being wrong
in the other direction costs them a warning they chose to ignore.

**The one exception is stop-work**, which still refuses. That is not the platform
second-guessing the operator: it is the operator's own emergency brake, pulled
deliberately, and honouring it is the entire point of having it.

Implemented in `backend/policy.py` as a pure function returning a typed
`PolicyDecision` with a stable reason code. `backend/enforcement.py` adapts it to
the ORM and returns the decision; only `stop_work_active` is converted into a
`403`. Warnings are returned to the caller and **not** written to `audit_logs` —
a scope finding is information for the operator, not a security event filed
against them.

| Reason code | Warns when |
|---|---|
| `engagement_not_active` | `engagement_status` is not `active` |
| `authorization_missing` | Non-bounty engagement with no authorization record |
| `authorization_not_active` | Authorization status is not `active` |
| `outside_testing_window` | Now is before `window_start` or after `window_end` |
| `stop_work_active` | The engagement's stop-work switch is engaged — **refuses with `403`, does not warn** |
| `target_out_of_scope` | No in-scope rule matches the target |
| `target_excluded` | An explicit exclusion matches |
| `scope_ambiguous` | Target matches both include and exclude at equal specificity |
| `capability_prohibited` | The requested tool is not permitted by the authorization |

### Scope matching rules

**Subdomains require an explicit wildcard.** `acme.com` authorizes only
`acme.com`. `*.acme.com` authorizes subdomains but not the apex; `*acme.com`
authorizes both. An earlier version treated a bare domain as covering every name
beneath it, silently authorizing `internal-admin.acme.com` — precisely the host
an engagement most often means to exclude.

**Exclusions are asymmetric and still cover subdomains implicitly.** Excluding
`prod.acme.com` also excludes `db.prod.acme.com`. Widening a deny is safe;
widening an allow is not.

**URL and API rules match on scheme, port, and whole path segments.** A rule for
`https://host:443/v1/admin` does not authorize `http://host:8080/v1/admin`, nor
`/v1/administrator`.

**Exclusions always beat inclusions.** When a target matches both, the result is
a warning — never "most specific wins", because an operator who wrote an
exclusion meant it.

**Ambiguity warns.** A target that cannot be resolved to a decision is flagged
rather than passed over silently.

### Three evaluation points

Policy is evaluated at **job creation**, again at **job claim**, and on the
`PATCH /jobs/{id}` transition into `running`. All three are required and none is
redundant — a job queued inside the window may be claimed an hour after it
closed, and PATCH is an independent route into execution that VardrRunner uses.

Evaluating at all three means the warning reflects the state at the moment work
actually starts, and it means stop-work engaged after queueing still halts the
job rather than applying only to future ones.

Transitions to `done` / `failed` are never gated: a runner must always be able to
report the outcome of work already performed, including after a stop-work.

### Bug bounty exception

`engagement_type == "bug_bounty"` engagements have no client and no signed
authorization — the programme's public policy is the authority. Those
engagements skip the authorization-record requirement; scope, exclusions,
engagement status and stop-work behave as they do everywhere else.

## Tenant isolation

Current: engagement-scoped resources route through `get_engagement_or_404`,
which returns **404 rather than 403** for a non-member — never revealing that
another user's object exists.

**Known gap (Phase 1b):** job, schedule, and client endpoints filter directly on
`owner_github_id == current_user`, bypassing membership. A teammate can read an
engagement's findings but not operate its jobs. The identity anchor is a GitHub
user, not an organization. Documented in `architecture.md` § Tenancy.

## Secrets

- API keys are stored as hashes, never plaintext.
- Credential values use `${VAR}` references resolved by the runner in the
  customer environment (VardrGate `internal/secretref`). The control plane
  stores the reference, never the secret.
- An unset reference is an **error**, not an empty string — a blank token turns
  an authenticated identity into an anonymous one, inverting a test's meaning
  while still reporting a clean run.

## Audit

`audit_logs` deliberately carries no foreign keys so records survive deletion of
the user or engagement they describe.

Scope warnings are **not** audited — they are advice to the operator, not a
finding against them. Stop-work engage/release is audited (`action="stop_work"`),
because that is a deliberate operator action with an incident behind it. The
`reason` and `detail` columns remain on the table, unused by the warning path.

## Data handling

- Evidence retention and sensitivity classification: Phase 2.
- Report exports must respect redaction and sensitivity: Phase 4.
- No credentials or tokens in URLs; no sensitive values in telemetry.

## Test coverage required

Every control above needs a test that fails when the control is removed.
`test_policy.py` covers the decision logic for all nine reason codes and the
scope-matching rules; `test_execution_policy.py` covers the wiring — that
findings surface as warnings at all three evaluation points, that a warned job is
still queued, that warnings are not audited, and that stop-work still refuses.
