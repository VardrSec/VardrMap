# VardrMap domain model

This describes implemented models, not a proposed future schema. The engagement
is the unit of work, performed for a client under an authorization.
See the [ORM models](../backend/models.py) for fields and the [API](api.md) for endpoints.
For installation, choose the distribution’s [Full setup](https://github.com/VardrSec/VardrSec/blob/main/docs/installation.md)
or [Mapless workflow](https://github.com/VardrSec/VardrSec/blob/main/docs/mapless.md).
Mapless uses Runner and Gate without a Map account or database; it does not share
this ORM state or automatically migrate it.

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
Manual jobs are claimed by an explicit Runner invocation. Separately configured
managed workers can discover and claim approved Gate jobs; starting Map or queueing
a job does not start a worker or authorize execution. A persistent worker can
serve successive independently approved jobs, not automatically repeat a completed
job. Existing manual workflows are not silently upgraded to managed execution.

`JobExecution` records an owned attempt, its bounded lease and capacity reservation.
Configured engagement concurrency, target and duration policies apply to budgeted
owned execution. Target spend and duration allocations are cumulative and
nonrefundable; duration allocation is not measured elapsed traffic, and concurrency
reservations are not a universal counter of processes on the host.

`ManagedEnrollment` binds an existing API key and Runner to an origin.
`ManagedApproval` retains the reviewed, separately signed approval and issuance
counters; `ManagedContract` binds one issued execution. Managed result and stop
receipts preserve the original outcome. `ManagedRuntime` and its attempt records
track admitted worker incarnations and job ownership. Admission and heartbeat
presence are not permission to execute a job. See the
[managed runtime protocol](managed-runtime-protocol.md) for finite and persistent
worker modes and the [security model](security-model.md) for enforcement limits.

Stop-work blocks new execution and requests cancellation of active controlled
attempts. A cancellation request is not a confirmed process exit; unresolved work
retains ownership/capacity until the applicable stop or completion protocol resolves
it. Legacy manual processes do not gain active cancellation from a policy warning.

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
are not part of this compatibility contract.

`RadarProgram` describes external bounty programmes and is not an engagement.
API keys and runner heartbeats remain user-bound. Raw API keys are not stored;
credential references in test cases are resolved in the execution environment.
Runner credentials remain user-bound, not organization-bound. Signed managed job
contracts and controlled running-process cancellation are implemented opt-in
capabilities, distinct from legacy manual execution and from broader organization
management. They require the matching Runner and explicit service configuration.

## Guidance

The original versioned API playbook catalog is served by Map and read by both the
case builder and Runner MCP. It stores guidance, not progress or evidence of coverage.
Saving reviewed cases, recording retests and committing client deliverable revisions
remain operator decisions. See [API playbooks](api-playbooks.md).
