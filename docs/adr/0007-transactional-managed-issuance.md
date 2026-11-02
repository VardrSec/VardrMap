# ADR 0007 — Transactional managed issuance, execution still disabled

Local NM-2 increment for independent review. It builds on the accepted wire
primitive and Runner ledger correction. No production keys, real association
provisioning, registered issuance route, queue worker or managed tool execution.

## Records and trust

`ManagedEnrollment` binds a configured Map origin, existing API-key record,
principal digest, Runner UUID, owner and revision. Only fixture/bootstrap code
can provision it; no enrollment/discovery endpoint exists. Approval keys remain
outside Map. `Issuer.review` authenticates the actual operator session and returns
unsigned facts; `register` verifies the separately signed receipt against enrolled
operator public keys, current owner facts and exact context. Ordinary API keys,
including full-scope keys, cannot register human approval. There is no approve
flag, approval-signing API or arbitrary signing API.

The strictly versioned authority digest covers the explicit authority record,
scope, configured Map origin, current engagement facts/ceilings and the specific
association/principal/Runner. Signed job IDs are the real ScanJob IDs; no aliases
or caller-supplied control-verification boolean. Runner remains the only full
plan/scope/runtime validator. The existing unsigned fact projector is reused;
current signed-record checks do not fabricate human-session provenance.

Approval rows retain exact envelopes, context, plan and spent count. Contracts
retain ordinal/attempt/fence and are unique per existing job. Existing
ScanJob/JobExecution allows one physical attempt per job; this first issuer does
not reopen a finished/unknown job or create retries. An approved N is an upper
ceiling, not a guarantee of N physical attempts in this profile. Unused count does
not require new approval merely because another attempt was contemplated; actual
multi-attempt job semantics remain unsupported. Standalone bounded reuse stays
unchanged. Unknown attempts are never refunded.

## Serialization and time

Lock order: engagement, job, approval, association, referenced API key, final
clock row. Mutable association/key/approval reads are refreshed under their locks,
including caller sessions with retained identity maps. Actual credential deletion
must linearize before issuance (deny) or wait for the issuer's key lock. The
configured origin and actual authenticated API principal must match the signed
association. A UUID by itself authenticates nothing.

The issuer atomically changes pending status, freezes the unchanged case, allocates
existing concurrency/target/duration controls and reserves the signed ordinal and
contract. Unique job/ordinal constraints and the conditional pending update give
one global winner. Fence 1 is globally unique for the one immutable owned attempt
of that exact job; this is not a general retry/fence allocator or consumption API.

Initial trusted time is observed in a short independent clock transaction.
SQLite then obtains an immediate writer boundary after authentication helper
commits and before authoritative reads; mutation paths obtain the same boundary
before refreshing their engagement. FOR UPDATE is not treated as a SQLite lock.
Distinct jobs cannot spend cached target/duration counters, and concurrent scope
writes cannot lose revisions. SQLite issuer calls require a clean session. An
unknown active native transaction is refused without committing or discarding
caller data, even when a flush has emptied ORM tracking collections. A helper-owned
writer transaction can reuse its boundary. PostgreSQL retains its row-lock order.
Permission work performs an atomic conditional high-water update under its own
transaction, so a later concurrent denial cannot be overwritten by an older
operation. This works on SQLite too, where FOR UPDATE alone is insufficient.
Signing/flush/parent-lock waits consume real elapsed validity; a final fresh
clock/window check precedes commit. Denials roll back ownership, ordinals,
contracts, case snapshots and all fees, then preserve trusted denied time in an
independent transaction. Payload times never establish the clock. Storage errors
deny; privileged database/host snapshot rollback remains outside authenticity.

Authorization create/update, scope add/delete/import, applied proposals, relevant
engagement/limit/stop/resume changes and case-spec edits share the parent lock.
Committed permission changes advance `managed_authority_revision`; reverting data
does not revert the revision. Ordinary advisory policy remains advisory. A stale
approval cannot be restored by a stop/resume or change/revert sequence.

`Issuer.current` verifies an owned contract tuple and current authority against
the actual capability/principal, but is unregistered and renews no lease, consumes
no contract and grants no execution. The tested mutation races either deny an
earlier change with zero committed fees or linearize issuance before a blocked
mutation, after which current verification rejects. This is not yet an actual
Runner online-control integration or proof of revocation stop latency.

## Compatibility, unsupported paths and rollback

`authorization_contract_required=true` is explicit on single fixed Gate job
creation; omission preserves the existing JSON/behavior. It can represent missing
approval from the start. Legacy claim/control/upload/completed-finalization
adapters refuse marked jobs. Contract-required pipeline requests are unsupported
and rejected rather than dropping the flag. Existing ordinary pipelines/jobs and
Gate case hashes/evidence semantics remain unchanged. Failure/cancellation
reporting can still close an owned fence; unknown state retains its reservation.

The schema is additive and initializes ordinary existing jobs to false, not a
silent engagement-mode migration. Approval/contract counters and association
tombstones are retained independently of job deletion. Downgrade refuses to erase
state. A rollback must retain compatible required-job guards; a backend predating
those guards is unsupported while marked work is reachable. Never clear flags,
reset counters or silently convert engagements to make old code accept work.

Future managed execution still needs reviewed HTTP issuance/control/consume,
operator-provisioned Runner trust, the shared validator/ledger, actual guarded
Gate dispatch and native final launch/cancellation boundaries. No missing
capability is advertised as Strict. Linux/Docker/ffuf control, workers, real
credential provisioning and full NM-2 acceptance remain open.
