# API engagement playbooks

Edition 1, 2026-10-11. Original Vardr guidance, tested against the controlled
fixtures in [integration acceptance](../scripts/integration/README.md).
These are operator runbooks; reading them queues nothing and grants no access.
They are not yet served as structured MCP playbooks or an interactive UI wizard.

## Common prerequisites and interpretation

Choose an engagement, record the client and written authorization, review the
testing window and permitted targets, and check stop-work. Policy warnings are
advisory; the operator decides whether the planned traffic is permitted. An
active stop-work prevents starting jobs.

Use dedicated identities and objects whose intended access you know. Store
credential references (`value_env` / `value_keychain`), not token values, in Map.
Confirm that the legitimate identity can reach the intended object before
interpreting another identity's response. A 401 for a stale token says nothing
about an ownership control. A 429, 503, redirect or transport failure is
inconclusive unless an explicitly reviewed convention establishes otherwise.

Record method, URL/parameters, object ownership, tenant and role context. Include
query variants and collection pages intentionally; one tested request does not
cover every parameter, object, page or HTTP method. Mutation requests require an
explicit Gate execution opt-in and fixtures safe to repeat per identity.

Runner's MCP `brief` and `methodology` prompts can help plan. MCP drafts cases but
cannot declare human review, save cases or commit a client deliverable. Complete
those decisions in the UI or the documented reviewed CLI workflow.

## Playbook API-01: object ownership and tenant separation

**Use when:** an operation reads a named user's record, document or other owned
object. **Expected artifacts:** reviewed case, per-identity execution evidence,
triage candidate if access disagrees, and a reviewed finding only after verification.

1. Capture the successful owner request with the Burp extension or
   `POST /engagements/{id}/api/exchanges`; inspect it in Review → API Surface.
   Confirm the actual owner/object and tenant from the agreed test data.
2. Draft a case through the case builder or
   `POST /engagements/{id}/test-cases/preview`. Select owner, same-tenant non-owner,
   other-tenant user, anonymous caller and an administrator if one is applicable.
   A draft's `skip` decisions must be reviewed; do not infer permissions from a
   successful response or the identity's name.
3. Set each expected decision, credential reference and resource ownership/tenant
   context. Declare real denial conventions, such as 404 for hidden objects or
   `deny_when.json_field` for an HTTP 200 error body. Save through the reviewed
   case builder or `test-cases save --reviewed`.
4. Queue `vardrgate_api_test` with the stored `test_case_id`. For a loopback lab,
   private-target opt-in is the local Runner operator's choice; it cannot be
   granted by backend configuration. Review actual execution statuses and
   outcomes, not just the job's completion badge or finding count.
5. Verify any `potential_bola`, `cross_tenant_access` or
   `missing_authentication` candidate with a legitimate baseline and protected
   response structure. Rule out public data, session expiry, a wrong object and
   documented delegated access. Promote only a verified issue to a finding.

**Common traps:** an error body behind HTTP 200; the wrong tenant; a login redirect;
API keys accidentally pasted into case JSON; a multi-parameter URL changed by
escaping; testing page 1 and claiming an entire collection; overreading a single
case as methodology coverage. The fixture exercises vulnerable and fixed controls,
declared 404/body denials, stale credentials, two pages and query preservation.

**Manual remainder:** deciding intended permissions and business impact, object
lifecycle/alias/batch variants, delegated access and write authorization. Gate
does not infer these from a response.

## Playbook API-02: privileged functions

**Use when:** an administrative operation should be restricted by role.
**Expected artifacts:** reviewed role expectations, legitimate admin baseline and
evidence for each tested identity.

1. Identify an admin operation from observed traffic or an API specification.
   Verify it is a privileged function; an `/admin` path alone is insufficient.
2. Choose the actual administrator, lower-role caller and anonymous identity;
   include tenant variants when roles are tenant-bound. Review allow/deny for
   each caller. Set `resource.required_role` and the intended `role_hierarchy`.
3. Prefer a read-only operation first. For mutations, use disposable objects and
   review the effects of repeating the request per identity before enabling them.
4. Queue the saved Gate case. Verify the admin baseline and inspect the lower-role
   execution. A `privilege_escalation` candidate needs a confirmed unauthorized
   capability or protected response, not merely a shared status code.
5. Repeat the same case after remediation and compare both runs. Keep failed,
   blocked and inconclusive executions visible.

**Common traps:** stale administrator credentials; interpreting a generic success
envelope as the privileged operation; applying a global role hierarchy to a
tenant-specific role; performing the mutation multiple times unintentionally.
The fixture checks both vulnerable and fixed admin functions.

**Manual remainder:** workflow/state changes, role delegation, background jobs
and impacts that require observing side effects beyond one response.

## Playbook API-03: evidence, retest and client handoff

**Use when:** a candidate is verified and needs a durable assessment record.
**Expected artifacts:** reviewed finding, linked evidence, finding activity,
retest evidence and an immutable client deliverable revision.

1. Review the candidate and create the finding with reproduction, impact and
   remediation. Preserve the execution evidence's hash and source. Map currently
   stores Gate evidence at engagement level; explicitly select the relevant
   identities/runs rather than guessing provenance from similar titles.
2. Link the evidence through the Evidence UI or
   `POST /engagements/{id}/evidence/{evidence_id}/link`. A linked record cannot be
   moved to another finding; it should remain an account of the original observation.
3. Record `retest` activity with the actual outcome and selected linked evidence.
   After remediation, replay the reviewed case and link its new evidence. Use
   `verified_fixed` only after the legitimate baseline still works and previously
   unauthorized identities receive the intended denial.
4. In Reports, create an engagement client report. Review scope, authorization,
   selected findings/evidence, methodology and limitations before committing a
   revision. Internal per-finding write-ups are separate records.
5. Download/review the report. Later source edits do not rewrite a saved revision;
   make a new revision when retest or editorial content changes.

**Common traps:** calling a transport failure fixed; reporting "OWASP covered"
because a tool ran; citing the wrong run's evidence; mixing a draft write-up with
a client deliverable; omitting unknown/untested operations from limitations.

**Manual remainder:** business impact, final report review and deciding what to
hand to the client. The acceptance harness simulates those operator decisions
on synthetic data; it does not automate professional sign-off.
