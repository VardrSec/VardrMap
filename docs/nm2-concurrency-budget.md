# NM-2 local increment — engagement concurrency reservations

Local implementation for independent review; whole NM-2 remains open.
Map coordinates capacity; Runner remains the execution engine. No worker, target
or duration budget, policy engine, enrollment system or packaging is added.

The engagement owner with current full-scope access explicitly configures
`PUT /engagements/{id}/concurrency-policy` with `{"limit":1}` (integer 1–1000).
Explicit `{"limit":null}` disables it only while idle. Missing, misspelled, unknown,
boolean or out-of-range fields are rejected. Runner keys and nonowners cannot
configure it; foreign engagements return 404.

Enabled policy requires an owned claim with `concurrency_budget:true`; legacy
and unbudgeted claims return 409. Runner explicitly selects
`jobs run --controlled --concurrency-budget` and requires a matching reservation
receipt, without fallback. Unconfigured engagements preserve default behavior.
Enable/change/disable requires no running jobs or unresolved reservations; no
existing engagement or work is silently migrated.

One reservation counts one owned Map attempt, including preparation, execution,
transport and finalization. It does not count targets, requests, child processes
or time. Unregistered direct/manual work and tools outside the protocol cannot
be counted. This is not a universal OS concurrency bound or global RPS cap.

Claims lock the engagement before counting reservations and changing job/attempt
state, in the same transaction. Count durable `capacity_reserved` records joined
to engagement jobs. Preserve engagement → job → execution lock order. Separate
engagements have independent locks and ceilings; duplicate claims cannot charge
twice. There is no check-then-increment operation outside the transaction.

Only matching owned `completed`, `failed` or `cancelled` finalization releases a
slot, at most once. Runner confirmation is trusted protocol evidence, not OS
attestation. Cancel requests, expired leases, lost connectivity and `uncertain`
outcomes retain capacity. A later matching confirmed terminal outcome may reconcile
uncertainty. There is no force release, expiry reaper or automatic fence reset.
Unowned PATCH cannot release ownership. Job deletion refuses reserved attempts;
engagement deletion refuses active/unresolved budgeted work. Reconfiguration cannot
clear reservations or enable a bound over uncounted running work. Existing
stop-work, partial evidence, grants and signed deadline fences remain.

Additive `0033concurrencybudget` follows `0032executioncontrol`. Old rows have no
policy/reservation. Downgrade refuses to delete accounting. Code rollback is not
protected operation: retain records and do not resume unbudgeted old claim paths
against enabled policy. Deployment and explicit migration are outside this work.

Acceptance requires PostgreSQL administrator/restricted-role competition,
policy-enable/update races, separate-engagement isolation, duplicate claims/finishes,
held cancellation/expiry/uncertainty, confirmed release, role/key/tenant denials and
retained migration data. SQLite verifies functionality, not row-lock concurrency.

Linux/Docker and ffuf controlled execution remain unsupported. No public/VPN,
fresh-host, managed signed approval or release gate closes here. Target/duration
budgets and all other mandatory NM-2 gates remain subsequent work.
