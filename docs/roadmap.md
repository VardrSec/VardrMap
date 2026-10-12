# Roadmap

Current backlog after the organization, evidence, API authorization and client
deliverable work. Shipped history lives in [CHANGELOG](../CHANGELOG.md).
[Domain model](domain-model.md) describes implemented entities, and
[implementation roadmap](implementation-roadmap.md) provides historical sequencing.

## Remaining platform work

- Schedule the physical `programs` table / `program_id` rename and retire legacy
  `/programs/*` aliases after coordinating every API consumer. This requires a
  production migration plan; do not drop or replace live tables opportunistically.
- Extend organization administration and team UI. Access predicates, organization
  membership, engagement invitations and viewer permissions already exist.
- Design organization-bound runner credentials and explicit credential permissions.
  Current API keys authenticate a user and may have runner-only scope.
- Specify signed/versioned execution contracts and cancellation of already running
  processes. Stop-work currently prevents starting work and skips schedules.
- Add engagement-wide concurrency/rate budgets; current tool limits apply per execution.
- Define automated evidence retention and export sensitivity rules. Metadata and
  redaction exist, but metadata alone is not a deletion or disclosure policy.
- Expand API methodology and real-binary, multi-platform integration coverage.
- Extend the original shared UI/MCP API playbooks and execution-backed assessment
  view beyond the initial ownership, roles and handoff guides. Claim-bound
  job/case/identity evidence and inconclusive outcomes are implemented.
- Extend identity setup with reviewed login/refresh support. Optional declared
  session preflight now checks principal metadata before authorization requests
  and retains bound failure diagnostics; automatic login/refresh is not implemented.
  See [identity preflight](identity-preflight.md).
  See [the platform comparison](platform-comparison-2026-10-11.md) and
  [starter API playbooks](api-playbooks.md) for priorities and acceptance criteria.
- Settle the [proposed remote MCP authorization design](adr/0002-remote-mcp-authorization.md)
  with VardrRunner before implementation: provider/hosting, grant binding, token
  lifecycle, organization access and whether to expose writes remotely remain open.

## Operational validation

Verify actual GitHub OAuth with separate accounts, deployed migrations and database
readiness, production CORS, notification delivery and cross-organization access.
Local test results do not establish production configuration or deployment success.
PostgreSQL CI and migration tests complement the default SQLite suite.
