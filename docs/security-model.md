# VardrMap — Security Model

## Threat model

VardrMap holds the authority to attack third-party infrastructure, plus the
evidence of successful attacks against it. The consequences of compromise are
asymmetric: a leaked finding is a disclosed vulnerability in someone else's
production system, and an unauthorized job is an unlawful intrusion attributed
to the operator.

| # | Threat | Control | Status |
|---|---|---|---|
| T1 | Testing outside authorization (expired window, revoked, out of scope) | Central policy engine, deny by default | **Phase 1a — this slice** |
| T2 | Cross-tenant read of another user's engagement | `get_engagement_or_404` → 404, never 403 | Implemented |
| T3 | Secrets leaking into findings, evidence, logs, reports | Centralized redaction | Phase 2 |
| T4 | SSRF via webhook or scan target | Resolve-and-block private/metadata ranges | Implemented (webhooks) |
| T5 | Stolen runner API key → arbitrary execution | Runner-scoped keys, hashed at rest, policy re-check at claim | Partial → **this slice** |
| T6 | Audit tampering | No FK constraints; append-only; survives subject deletion | Implemented |
| T7 | Denial of service against a client | Rate/concurrency limits in job envelope | Phase 3 |
| T8 | Prompt injection into AI triage | No raw secrets to model; human approval before intrusive action | Phase 2 |

## Default deny — the core control

Execution is denied unless every condition passes. Implemented in
`backend/policy.py` as a pure function returning a typed `PolicyDecision` with
a stable reason code.

| Reason code | Denies when |
|---|---|
| `engagement_not_active` | `engagement_status` is not `active` |
| `authorization_missing` | Non-bounty engagement with no authorization record |
| `authorization_not_active` | Authorization status is not `active` |
| `outside_testing_window` | Now is before `window_start` or after `window_end` |
| `stop_work_active` | The engagement's stop-work switch is engaged |
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
deny — never "most specific wins", because an operator who wrote an exclusion
meant it.

**Ambiguity is deny.** A target that cannot be resolved to a decision is denied
rather than allowed, and the denial is audited.

### Two enforcement points

The policy is evaluated at **job creation** and again at **job claim**. Both are
required and neither is redundant:

- A job created inside the window and claimed an hour later, after the window
  closed, must be denied at claim.
- A job created while the engagement was active and claimed after stop-work was
  engaged must be denied at claim.

A single check at creation would make the testing window advisory.

### Bug bounty exception

`engagement_type == "bug_bounty"` engagements have no client and no signed
authorization — the programme's public policy is the authority. Those
engagements skip the authorization-record requirement but **still enforce
scope, exclusions, stop-work, and engagement status**. This is the only
carve-out, and it is deliberate: requiring a signed SOW for bounty work would
make the product unusable for it.

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
the user or engagement they describe. This slice adds `detail` to record the
policy reason code, and audits **denials as well as actions** — a denied
execution attempt is the security-relevant event.

## Data handling

- Evidence retention and sensitivity classification: Phase 2.
- Report exports must respect redaction and sensitivity: Phase 4.
- No credentials or tokens in URLs; no sensitive values in telemetry.

## Test coverage required

Every control above needs a test that fails when the control is removed. This
slice ships tests for all nine deny reasons, both enforcement points, the bounty
carve-out, and exclusion-beats-inclusion.
