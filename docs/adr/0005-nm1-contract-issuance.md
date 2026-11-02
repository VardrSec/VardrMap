# ADR 0005: NM-1 contract issuance and approval snapshots

Status: Accepted direction, 2026-11-01; read-only prototype adapter only.

`backend/nm1_authorization.py` projects actual engagement, explicit authorization,
scope, stored case and pending Gate job facts into an unsigned owner review request.
It is not registered as an HTTP/MCP route and performs no database mutations.
Runner owns the reference schema, signing/validation and conformance fixtures.

Require trusted operator-session provenance and the engagement owner. Ordinary
API keys, runner keys, agent-supplied review flags and nonowners cannot approve.
An unsigned projection is never executable permission. Protect the approval-signing
key from agents/workers; the prototype receipt is an explicit operator assertion.
Future authenticated Map approval records can supply the same reviewed context.

A human approval may authorize N unchanged-plan executions within its validity,
scope and limits. Each issued contract reserves one ordinal and one attempt. A
changed snapshot or exhausted count needs new approval; an ambiguous launch is not
automatically refunded/replayed. Case review remains distinct from execution approval.

Select authorization by explicit engagement-bound record ID and bind its snapshot
digest. Existing rows are mutable, and the active-authorization read and policy
adapter currently select records differently. No automatic fallback to an older
active record can grant v1 permission. The prototype narrows scope to every actual
request descriptor, including Gate auxiliary requests, and requires existing policy
to permit each destination. The common Runner validator must still reconstruct the
plan from the actual unresolved case before issuance/consumption.

Future claims must atomically check approval/authority revisions and stop-work,
authenticate an enrolled per-Runner credential, allocate attempt/fence and persist
the signed receipt before returning it. Mutations/results must match that fence.
UUID/hostname alone is not authentication. Fencing does not cancel active traffic;
live leases/cancellation and workers remain NM-2. No such endpoint, migration or
service is added by this prototype. Legacy advisory jobs and case hashes are unchanged.

Rollback removes the unregistered adapter/prototype docs. No existing data or
engagement mode has changed, and no new migration needs downgrading.
