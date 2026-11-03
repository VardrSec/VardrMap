# ADR 0009 — Managed evidence, completion and retained reconciliation receipts

Status: local unregistered prototype; activation and independent acceptance separate.

`managed_results.Results` reuses the issuer's clock/transaction boundary and the
owned principal/capability/Runner/origin/job lock order. It requires a consumed
exact contract/attempt/fence and matching signed-envelope SHA-256. Evidence and
status inspection may proceed after approval expiry or revocation because neither
operation grants execution. An invalid API key, foreign owner or viewer still
cannot use these operations.

## Evidence transaction

The sender supplies the exact bounded UTF-8 Gate artifact and SHA-256. Duplicate
JSON keys/nonfinite values, oversized data, a changed hash, an absent/different
frozen case hash or case ID are refused. The parsed result uses the existing Gate
upload schema and the same redacted evidence, assessment and candidate projection.
No scanner signal is promoted to a confirmed finding or independent assurance.

The shared projection helper commits nothing. Evidence, the existing result
receipt and a retained `ManagedResult` row commit together. Identical raw artifact
replay returns the original receipt; a changed artifact is refused. Legacy upload
keeps its original guard, canonical receipt hashing and notification no-op on
replay. There is no managed flag override in the legacy route.

The new additive `0037managedresults` table stores only binding hashes, IDs, counts,
preflight-failure status and terminal receipt state. It has no destructive backfill
or cascading FK; tombstones survive job deletion. Downgrade refuses to erase these
receipts. A deleted/inaccessible job is not made accessible through inspection.

## Completion and observation

Completion requires the matching result receipt and the authenticated Runner's
literal known-termination assertion. This is not independent OS attestation.
A completed outcome requires current signed authority, no failed preflight, a live
owned lease, original duration and unexpired grant/window bounds. Checks run again
after writes so elapsed validity rolls back release and terminal state together.
A known failed/cancelled outcome may be reported after expiry/revocation; expiry
alone never finalizes or refunds an attempt. Approval ordinals, represented target
charges and allocated duration are never refunded. Only concurrency capacity is
released when that exact owned terminal result commits.

A terminal outcome is immutable. Exact replay returns its receipt without renewing
permission; changed outcomes or inconsistent retained control state deny.
Inspection authenticates the same ownership tuple and observes the exact result
and terminal receipts without renewing, completing, releasing or retrying work.
Clock/auth telemetry may retain their existing observations. Missing evidence,
missing capabilities and unknown execution remain conservative holds.

No production HTTP route, queue worker, trust enrollment, deployment or release
pin changes. Test adapters use synthetic keys and disposable databases/loopback
TLS only. Real Windows/Gate finalization and containment remain an explicit gate
for Papachin, and the designated independent reviewer retains acceptance authority.
