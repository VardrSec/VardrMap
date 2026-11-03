# NM-2 local slice — cumulative represented-origin attempts

This implements part of roadmap D07/NM-2, not phase completion or managed signed
authorization. One work unit is one distinct canonical HTTP(S) origin represented
in a fixed Gate case, per owned attempt. Count resource, setup, every identity
preflight (including verifier), verification and reset origins, even when a branch
may not execute. Deduplicate within one attempt; charge again for every new
attempt. Normalize scheme/host/default port using existing case-origin parsing,
with fixed-profile ASCII/IP restrictions and explicit ports. Count logical HTTP
origins, not DNS, proxy/TLS transport connections, requests, paths or unique IPs.

Only the existing `gate-fixed-http/1` request-guard profile is supported. Runner
compiles it from the unresolved case before claim and passes its guard to actual
Gate execution. Dynamic capture/substitution, unsupported execution settings and
other tool profiles refuse. No universal network coverage or RPS claim is made.
Ordinary direct/manual work outside the owned protocol cannot be counted.

Full-scope current owner explicitly sets `PUT /engagements/{program_id}/target-policy`
with required `{"limit": N}` (1–1000000). Unknown/missing/malformed fields refuse.
Runner uses `jobs run --controlled --target-budget`, optionally combined with
`--concurrency-budget` and `--expiring-grants` if separately configured. Default
unconfigured engagements and default invocation remain unchanged. Configured
engagements refuse legacy/unbound claims and unsupported profiles.

Map compares the caller's profile, unresolved case SHA-256 and sorted canonical
origin set with its case snapshot. A successful conditional claim charges the
whole set and creates owned execution in the same engagement-locked transaction.
Losing/duplicate claims do not spend. The receipt binds the exact job ownership and
target binding, charged count, total spent and ceiling; Runner refuses absent or
mismatched bindings, counts or limits. This is authenticated protocol metadata,
not a signed v1 execution approval. Existing case hashes and evidence are preserved.

Durable `programs.targets_spent` never decrements, even after a known prelaunch
failure following claim: the measured unit is admitted attempts, not contacts.
Completion, failure, cancellation,
uncertainty, expired leases and lost connectivity do not refund potentially used
allowance. Deleting a terminal job does not reset the engagement total. Engagement
deletion refuses once spend exists; disable after any spend also refuses. There is
no reset, force-refund or reaper. Idle owner changes may adjust a ceiling only at
or above spent, preserving the total. Enable/change/disable require no running or
unresolved owned work, so enabling cannot adopt uncharged active work silently.
Before first spend, explicit idle disable is permitted. Accounting covers the
explicitly activated protocol, not unmeasured historical/manual activity.

Additive migration `0034targetbudget` follows `0033concurrencybudget`. Existing
engagements start unconfigured with zero protocol spend, not an assertion of no
historical work. Owned attempts retain charge/binding metadata. Downgrade refuses
to discard accounting; code rollback must retain data and must not be represented
as protected operation. Restore a verified backup only after independently
reconciling all fences and spent allowance. No deployment is authorized here.

Tests must include competing claims, actual separate-engagement claims, duplicate
finalization, deletion/configuration persistence, unknown outcomes, exact binding,
auxiliary origins and real policy-enable/disable races in administrator/restricted
PostgreSQL roles. Fixture cleanup may reset only disposable test state; no product
reset endpoint exists. Real Gate loopback evidence must verify guarded dispatch.

Duration budgets, managed signed approval, worker/readiness and other NM-2 gates
remain open. Linux/Docker and ffuf controlled execution remain unsupported. Existing
public/VPN/fresh-host and release exclusions remain; no distribution pins change.
