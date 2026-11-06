# Inactive persistent runtime protocol

This is an implementation candidate, not accepted deployment or live authority.
`Runtimes(results, persistent_enabled=False)` remains the production default;
isolated tests inject the opt-in. The
[frozen cross-component contract](https://github.com/VardrSec/VardrSec/blob/efd95bed5b0f254dca78f3f9d49a93576536014d/docs/nm2-persistent-worker-contract.md)
records the availability requirement and separate reporting-lifetime decision.

## Authority and immutable admission

V3 explicitly selects `mode: "persistent"`. Optional `limits.max_attempts` is NULL
or a canonical positive ASCII decimal string through `9223372036854775807`;
`idle_timeout_seconds` is NULL or a strict integer in `1..86400`. Default NULL
limits impose no 60-second idle or 32-job cap and never mean legacy v1. Every
job still needs human approval, original enrolled key, shared validation, current
expiring grants, finite execution ceilings and atomic budgets. Admission and
presence supply none of those permissions. Unknown state is never retried/refunded.

Registration reuses the existing owner-session boundary; a Runner key cannot
approve an incarnation. The body contains existing enrollment/Runner/origin,
six-field identity and capability hash plus mode, limits and exactly
`reporting_authority: {purpose: "worker-stop-only", expires_at: null}`. Legacy TTL
and top-level attempt-limit fields are forbidden in v3. Admission `/3` adds
`admission_sha256`, the canonical digest of every other admission field. The
six-field runtime hash stays unchanged. Stored snapshot/policy is immutable;
re-registration cannot upgrade, repair, extend or revive an incarnation. A digest
correlates bytes; it is not remote attestation.

The proposed STOP grant lasts until explicit revocation or physical retirement.
It cannot claim, consume, refresh, publish success or refund budgets. This extends
ADR 0043's reporting lifetime and needs a concrete owner disposition before live
activation. The trusted-host false-exit risk remains: a compromised host/secret
holder could prematurely release concurrency. Component tests accept no risk or
platform gate and create no default startup work.

## Operations and status

Existing paths use bind `/3`, idle-release `/2`, selected history `/2`, current
observation `/3`, original-key observation `/4` and retirement `/3`, carrying the
immutable admission hash and decimal-string sequence. Generic job receipts and
original tokens are unchanged. The generic association fingerprint still binds
origin, Runner and principal. Exact historical lookup uses
`/managed/runtimes/{id}/attempts/{sequence}/receipt` with runtime/admission hashes;
it never returns an unlimited array. Current observation adds a structured cursor
`{last_sequence: "N", phase: "active"|"idle"}`, active binding/receipt, retirement,
`new_work_disabled`, `reporting_revoked` and advisory availability.

`POST /managed/runtimes/{id}/disable` uses existing host STOP authentication and
the two hashes. It blocks discovery/new claims only; it does not cancel a bound
job, revoke reporting, release capacity or forbid normal bound control/terminal
release. Distribution stop separately stops the exact physical incarnation.
Stop Work and local cancellation retain their own meanings. The fixed disable
`/1` ACK binds runtime ID, hashes, the true flag and full receipt digest. Resolve
a lost reply read-only, never infer replay rights. Owner reporting revocation
also disables new work and may leave recovery held.

Authenticated persistent discovery reports an exact idle cursor only after
local owner/no-hold checks; matched current/refresh can report active presence.
Its freshness is 15 seconds. Stale, mismatched, disabled or revoked presence is
held; retirement is stopped. Host status must also inspect the exact daemon
incarnation. Presence neither proves native readiness nor renews a lease.

## History, release and recovery

Additive `0041persistentruntime` preserves finite v1/v2 rows and byte shapes.
Signed BIGINT counters, composite predecessor/parent foreign keys and exact
head/active pointers retain every v3 attempt. Indexed head, predecessor and
selected reads replace a full history scan; missing/conflicting/orphaned history
refuses. No deletion, eviction or truncation is exposed. Downgrade and code-only
rollback over v3 state are unsupported; retain/reconcile state before restoring
an independently verified backup.

Only consumed, confirmed work with a canonical completed or failed **result**
completion and released capacity may close its slot. Stop, cancelled,
nonterminal, physically retired and unknown work cannot release for reuse. The
client must independently prove normal native return, empty lineage, sealed and
joined Control, durable terminal ACK and native DONE. `native_done_sha256` is
correlation, not remote native attestation. Confirmed-stop partial evidence is
not the naturally failed reuse lane.

Claim/current keep parent/job/contract/approval locks before Runtime, and Runtime
before the first ManagedClock lock. A trusted optional control hook adds no
policy engine. Physical reports choose one cursor/job, lock then recheck it and
never retarget. Observations avoid Runtime-before-receipt lock inversion and
refuse a changed projection signature.

Original-key `/4` checks original principal, fingerprints and exact admission/
history. An absent claim is only a snapshot. Exact physical retirement may prove
a requested sequence was never issued; that permits only narrow local metadata
retirement, never a token, consumption ACK, retry, refund or success. Lost/revoked
original keys remain held.

## Acceptance still required

Long idle, more than 32 jobs, large exact counters, optional limits, disable/stop,
migrated history constraints, real PostgreSQL races and the full original failure
matrix need evidence. Actual Linux/Docker Desktop and the live owner disposition
remain separate. No stopped adversarial experiment, release, component pin or
NM-3 continuation is authorized by this candidate.
