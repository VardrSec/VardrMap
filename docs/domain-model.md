# VardrMap domain model

This describes implemented models, not a proposed future schema. The engagement
is the unit of work, performed for a client under an authorization.
See [architecture](architecture.md) for field details and [API](api.md) for endpoints.

## Relationships

Organizations and organization memberships provide shared access. Engagements
retain direct ownership and invitation membership for compatibility. Clients can
be shared through an organization; engagement invitations do not grant access to
the underlying client record. Organization viewers may read clients but cannot edit or delete them.

An engagement owns authorizations, scope, assets, evidence, reconnaissance,
services, scanner candidates, findings, test cases, jobs and deliverables.
`AssetRelationship` provides graph edges; findings and evidence can reference assets.
`ApiEndpoint` and `ApiExchange` store discovered API surface and redacted exchanges.
`AuthorizationTestCase` holds reviewed authorization tests, including the Gate spec.
Preview drafts are separate from saving reviewed cases and queue no work.

`ScanJob` represents execution; `JobResultLink` preserves observations when deduplication
reuses an existing recon, scan or service row. `JobResultReceipt` supports idempotent uploads.
Gate jobs freeze the unresolved reviewed case in `case_snapshot` at claim and store a
separate `assessment` on upload. Runner's `case_hash` binds the artifact to that snapshot;
legacy unbound uploads remain usable but inconclusive. Lifecycle `done` is not an
assessment verdict, and conclusive completeness can still contain violation candidates.
There are no recurring scans: each job runs once, when an operator runs `vardrrunner jobs run`.
Per-execution limits do not create an engagement-wide traffic budget.

`ScanItem` is a scanner candidate. Dalfox payload and match evidence are preserved
as reported; raw evidence requires safe rendering, not destructive HTML sanitization.
A `Finding` is an operator-managed issue. `FindingActivity` records snapshots,
remediation notes and retest outcomes; finding status alone does not prove remediation.
`Evidence` has content hashes, collection provenance, redaction and sensitivity/retention metadata.
Gate evidence also records job/case references, logical case id, identity, expected
decision and observed outcome. Deleting a job or case clears its foreign-key reference
without deleting retained evidence; historical/manual provenance is not inferred.
Retention metadata does not mean automatic deletion is enforced.

`Report` is a finding write-up. `EngagementDeliverable` and `DeliverableRevision`
represent client deliverables with immutable content snapshots and hashes;
revision workflow status can change. Reviewed evidence associations retain provenance.
`AuditLog` deliberately lacks subject foreign keys so deleting a subject does not
remove its audit trail.

## Naming and boundaries

The ORM class is `Engagement`, but the table remains `programs` and foreign keys
remain `program_id`. `/programs/*` is a compatibility alias for `/engagements/*`.
Do not introduce a second engagement table. Physical renaming and alias retirement
remain scheduled work.

`RadarProgram` describes external bounty programmes and is not an engagement.
API keys and runner heartbeats remain user-bound. Raw API keys are not stored;
credential references in test cases are resolved in the execution environment.
Broader organization management, organization-bound runner credentials, signed job
contracts and running-process cancellation remain distinct future capabilities.

## Guidance

The original versioned API playbook catalog is served by Map and read by both the
case builder and Runner MCP. It stores guidance, not progress or evidence of coverage.
Saving reviewed cases, recording retests and committing client deliverable revisions
remain operator decisions. See [API playbooks](api-playbooks.md).
