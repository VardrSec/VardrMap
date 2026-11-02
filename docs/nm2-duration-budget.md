# NM-2 local slice — cumulative allocated permission seconds

This addresses roadmap D07/NM-2 at a deliberately stated scope. The durable unit
is **allocated wall-permission seconds per owned attempt**, an integer 1–86400.
Map sums allocations against an explicit engagement ceiling. Allocation is not
measured consumption, CPU time or actual scan duration; no unused time is refunded.
Manual/unregistered work and other execution outside this protocol are uncounted.

The full-scope current engagement owner configures
`PUT /engagements/{program_id}/duration-policy` with required
`{"limit_seconds": N}` (1–1000000000). Missing/extra/malformed fields refuse.
Idle explicit null disables only before any allocation. Policy changes require no
running or unresolved work and cannot reduce the ceiling below allocated total.
Deletion of an allocated engagement refuses. No reset, refund or expiry reaper.
Existing unconfigured/default engagements and manual CLI remain unchanged.

Runner explicitly requests `jobs run --controlled --duration-budget SECONDS`.
The CLI and library execution entries reject invalid/noncontrolled requests before
network/process activity. Map refuses missing finite allocation on configured
engagements, or allocation requests without configured policy. A successful
conditional owned claim allocates and creates ownership in the same engagement-
locked transaction. Losing/duplicate claims allocate zero. Concurrent target and
duration failures roll back together; concurrency reservations remain independent.

The authenticated owned receipt binds job/Runner/origin/capability plus exact
requested seconds, total allocated and ceiling. Runner refuses absent/mismatched
or noninteger values without fallback. Owned attempt allocation and engagement
total persist through completion, cancellation, failure, expired leases, crashes,
unknown outcomes and terminal job deletion. Duplicate finalization never refunds.
The receipt is not signed v1 authorization or human execution approval.

## Enforcement boundary

Runner captures `time.monotonic()` immediately before its claim HTTP call. Claim
latency and all subsequent preparation consume the window. Preclaim review,
target resolution and local setup are outside it. A late response or renewal does
not restart the clock. Each owned-claim facade is single-use, including unknown
responses, so duplicate calls cannot renew the anchor. Monitor entry is also
atomically single-use, including failed setup. The immutable monotonic deadline
composes by minimum with
existing local per-tool timeouts and signed authorization deadlines. Existing
grant checks remain independently necessary.

Actual creation checks run after private-file/environment/native preparation,
grant-lock waits and the controlled permission callback. Expired preparation may
finish late, but cannot launch a process. This does not preempt a blocked provider,
filesystem or OS creation call at a civil-clock instant. Active owned process-tree
supervision checks permission on its existing approximately 0.05-second cadence;
clock changes cannot extend an allocation. Local I/O, scheduling and OS stalls
prevent a universal hard stop-time claim.

Expiry uses the existing graceful-then-forced cleanup: up to two seconds grace,
then force and up to two seconds verification, conditional on responsive OS/local
storage. Processes may still issue traffic during grace. Cleanup is additional to
the permission window, not silently counted as measured usage or a hard network
cutoff. Failed/uncertain termination preserves partial evidence and fences.
Post-tool artifact validation, upload and finalization are outside this duration
bound; existing owned control leases/stop-work still protect their lifecycle.
This is not a hard total job-duration cap or aggregate RPS guarantee.

Map coordinates accounting; Runner alone executes. Current native controlled
profiles are eligible, subject to their independent support limits. Combining
target ceilings still requires fixed guarded Gate; combining expiring grants
still requires Gate reference support. Linux/Docker and ffuf controlled execution
remain unsupported. No new dependencies, policy engine, worker or enrollment.

Additive `0035durationbudget` follows `0034targetbudget`; old engagements remain
unconfigured with zero protocol allocation, not an assertion of no historical use.
Downgrade refuses to delete accounting. Code rollback is not protected operation;
retain allocation records and reconcile all fences before any verified restore.

Acceptance distinguishes allocated seconds from measured preparation, process
runtime until stop request, cleanup until verified termination and end-to-end
fixture time. Verify receipt mismatch, late response, clock change, strictest
deadline, zero-launch delays, forced shutdown, unknown/crash persistence, actual
separate-engagement claims and PostgreSQL policy/claim races in both roles.
Managed signed approval, broader runtime/connectivity/restart acceptance and the
opt-in least-privilege worker remain open. No phase, deployment or release closes.
