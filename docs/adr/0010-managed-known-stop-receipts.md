# ADR 0010 — Retained owned known-stop receipts

Status: local unregistered prototype; independent review/activation remain separate.

`managed_stops.Stops` supplies a distinct reporting lane for consumed managed work
that stopped without a complete artifact. It reuses existing owner, API principal,
capability, origin, Runner and exact contract/attempt/fence/hash checks. Request,
expiry, lost connectivity, PID disappearance and an unknown process tree do not
establish a stop. The authenticated Runner must assert literal known termination
and an allowlisted fixed cause/outcome; this is not independent OS attestation.

Local/remote emergency stop is cancelled. Lease/authorization expiry, unavailable
control cap, timeout and retained descendants after exit are failed outcomes once
native termination is confirmed. Known reporting may occur after permission expiry
or revocation without renewing permission or granting another execution. Invalid
credentials, wrong capabilities and non-writers still cannot mutate owned work.

Within the established parent/job/execution transaction, one immutable stop receipt
and its exact terminal state commit together. Only concurrency capacity is
released. Contract consumption, approval ordinal, represented targets and allocated
duration remain spent. Duplicate identical reports return the original receipt;
changed causes/outcomes and inconsistent retained execution state are refused.
A result protocol already in progress cannot be overwritten through this lane.
No empty result or fabricated evidence is created. Evidence submitted separately
after a stop stays forensic; it cannot reopen or successfully complete the job.

The additive `0038managedstops` table has no cascading FK and retains IDs, fixed
cause/outcome, hashes and finish time after job deletion. Downgrade refuses erasure.
Read-only business-state inspection authenticates the same tuple and returns the
exact receipt, without retry, renewal, termination inference or release. Existing
clock/auth telemetry may retain their ordinary observations.

No production route, worker, enrollment, publication or deployment is enabled.
Synthetic ASGI/TLS and migrated PostgreSQL fixtures check protocol, retention and
atomicity. Real Windows/Gate stop receipts and containment remain a Papachin gate.
The owner has waived the hosted development backup prerequisite, accepting
unrecoverable disposable-data risk; this does not waive migration review, security,
CI, Windows or independent acceptance, and does not permit deletion of control
records or unrelated infrastructure.
