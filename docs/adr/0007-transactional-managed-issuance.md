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
Legacy claims, owned execution mutations and reservation deletion share this
writer boundary; stop-work refreshes its revision inside it. Owned control also
refreshes cached execution state before deciding whether permission remains live.
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

### Synthetic HTTP integration boundary

The unregistered `Issuer.refresh` reuses `current` validation and the owned
capability checks in one transaction. It renews only an already live attempt;
the ten-second ceiling is also capped by the signed approval/window/grant
expiries and original job start plus allocated/approved duration. A denial,
including permission elapsed during flush, rolls back the renewal. `current`
remains a non-renewing check. Neither method is registered in the production API.
The refresh reply includes the actual stored UTC `lease_expires_at`. The test
probe caps each renewal by that fixed expiry through its trusted UTC/monotonic
anchor as well as the request-start lease bound. Replaying old JSON cannot move
permission beyond the last actual server renewal, including client wall rollback.
This bounded lease does not promise instantaneous revocation between observations.

`tests/test_managed_http.py` opts in with `NM2_RUNNER_SOURCE` pointing to the
matching isolated Runner checkout. It loads only Runner's test probe and exercises
real JWT/local-session/CSRF authentication and JSON transport through a test-only
ASGI app. The only dependency override supplies a disposable database; policy,
signatures, compiler, validator, ledger and final launch guards are real components.
The probe ends at an inert callback, not a process or HTTP target dispatch.
ASGI HTTPS is an emulated request scheme, not TLS deployment evidence. The tool
digest and signing seeds are synthetic; they prove binding, not binary provenance.

Run this opt-in suite only in an isolated child with an OS environment allowlist,
dotenv disabled, disposable profile/database and public fixture keys. Ordinary
backend tests skip the cross-repository harness when the explicit source is absent.
This test bridge does not add a runtime code dependency between applications.
Map's retained `consumed=False` remains unchanged even when the disposable Runner
ledger reserves permission. Distributed consumption/acknowledgement/recovery and
exactly-once execution remain unresolved. No real trust, enrollment, production
route, queue/worker activation, Gate execution or support expansion follows.

### Disposable loopback HTTPS evidence

The separately opted-in `tests/test_managed_tls.py` sets `NM2_TLS_LOOPBACK=1`
alongside `NM2_RUNNER_SOURCE`. It reuses the same test-only app and probe over
real loopback TLS sockets. Its temporary CA, named server certificate, private
key, profile and database are disposable; no machine trust or installed settings
are changed. Named-chain verification remains enabled, including strict X.509
checks. Certificate negatives assert the actual trust/hostname/expiry failure;
connection refusal asserts the real underlying refused-connect classification
using a fixture-owned bound non-listening port and a valid CA path.

Runner's test transport uses `api.py`'s existing `VardrMapClient` and session.
Only those fixture instances disable retries/redirects, select the explicit CA
file and bound timeouts. Existing manual clients retain their defaults. API-key
and local-cookie redirects must not reach either a same-origin HTTPS sink or a
plain HTTP sink. Wire truncation/read timeout after a real claim or renewal
preserves uncertain ownership and cannot extend the client's last known lease.
Cached replies retain their original server expiry through clock rollback.

The server binds only loopback and is stopped and joined by the fixture. The
final callback is still inert. This proves this host's synthetic TLS transport,
not production deployment, persistent trust/enrollment, fresh-host/public/VPN
compatibility, Docker networking, Gate dispatch or distributed exactly-once
execution. All later activation and support gates remain open.

### Explicit native Gate fixture

`tests/test_managed_native.py` additionally requires `NM2_NATIVE_GATE=1` and a
verified existing development Gate binary/receipt and guarded fixture source. The
isolated launcher pins those bytes before any tool contact. Native policy uses real
UTC and monotonic time and fresh synthetic signatures; deterministic ASGI clocks
and the synthetic tool fingerprint are not used as native execution evidence.
Only the disposable child enables private loopback access. Existing installations,
trust stores, release pins, production routes and retained data are unchanged.

The fixture invokes Runner's actual handler/control/WindowsJob against an owned
loopback resource. It checks healthy renewal past ten seconds, preparation denials,
auxiliary requests, private-file cleanup, real cancellation/stop/grant and control
faults. Active cases verify the intervention and expected stop cause, last verified
lease and existing cleanup bound, excluding eventual unrelated tool timeout as a
false positive. Truncated post-commit renewal is labeled lost response; a separate
owned TLS-server shutdown proves actual connectivity loss. Success artifacts remain
local and case-bound. All cases retain Map ownership/counts; no legacy completion,
upload or false failed outcome is used to make the test pass. Distributed consume,
ACK, recovery, managed evidence/completion and production activation remain open.

### Preserved compatibility

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
