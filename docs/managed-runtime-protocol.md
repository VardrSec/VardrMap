# Managed runtime admission and host stop receipts

This is the bounded ADR 0043 implementation protocol. It is disabled by default
and requires explicit worker configuration, an existing issuer, operator public
trust, a separate Map contract-signing key and an existing Runner enrollment.
Protocol tests do not establish Docker termination or platform acceptance.

Omitting `max_attempts` retains the one-attempt v1 protocol below. Explicit v2
sequencing is a development candidate; source protocol tests do not complete its
native descendant-drain or installed worker acceptance.

## Bounded healthy sequencing (v2)

Additive schema `0040runtimesequence` preserves v1 records without inferring a
sequence history. Registration may explicitly add integer `max_attempts` (1–32);
even explicit `1` selects admission `/2`, whose only added key is `max_attempts`.
Null, boolean, fractional or out-of-range values refuse. Exact registration replay
cannot change this selection, extend TTL or upgrade the same physical incarnation.
The six-field identity and capability purpose hash are unchanged.

Schema CHECKs forbid v2 rows from acquiring legacy binding columns or a retired
marker without retained non-null retirement JSON. SQLite migration batch
copy preserves existing v1 rows and uniqueness; PostgreSQL uses ordinary additive
ALTER statements. These backstops reject unsupported old writers, and do not make
code-only rollback over enabled v2 state supported. Retain history and reconcile
ownership before any independently verified recovery procedure.

V2 managed claim adds exact next `runtime_sequence` (1–32) to the runtime ID/hash.
Under Runtime before Clock, the existing claim transaction appends an immutable
attempt binding and advances `last_sequence`/the active pointer. No next claim is
allowed while an active binding exists, after retirement/expiry/revocation or above
the fixed ceiling. Every job still needs its own signed approval, grants, budgets
and independently validated contract; no job is reopened or retried. Runtime-bind
`/2` adds `runtime_sequence` to the existing flat acknowledgement.

Only canonical `completed` work that is consumed, runtime-confirmed and has released
capacity may use `POST /jobs/{job_id}/managed/runtime-idle-release`. It requires the
current original enrolled key, original execution token and active unrevoked runtime
grant. Its body is the existing consumed tuple/token plus runtime ID/hash/sequence,
`terminal_receipt_sha256` and `native_done_sha256`. The terminal digest hashes the
**full canonical completion object**, not its embedded result-receipt SHA. The DONE
digest correlates the trusted worker's validated native DONE/drain acknowledgement;
Map cannot independently attest it. The worker must first retain local completion,
drain descendants and quiesce its old control loop.

The exact release acknowledgement is:

```text
{schema:"vardr.worker-idle-release/1", runtime_id, runtime_sha256,
 runtime_sequence, binding, terminal_receipt_sha256, native_done_sha256,
 released:true, receipt_sha256}
```

Its digest covers every preceding key. The transaction retains this receipt and
completion snapshot, then clears the active pointer without refunding anything.
An exact explicit replay observes the same receipt; changed input refuses. The
worker requires a durable ACK before reusing the slot. Lost ACK, failed/cancelled
work, forced exit or unknown ownership holds/exits; none creates reuse rights.

Host `/receipt` on v2 returns exact keys `schema` (`vardr.worker-receipt-observation/2`),
`runtime_id`, `runtime_sha256`, `last_sequence`, `active`, `retirement`. Active is
null or `{runtime_sequence,binding,receipt}`; its job receipt alone never proves
whole-container exit. Exact historical lookup is
`POST /managed/runtimes/{runtime_id}/attempts/{runtime_sequence}/receipt`, with the
same `{runtime_sha256}` body and stop-capability authentication. Its keys are schema
`vardr.worker-attempt-observation/1`, runtime ID/hash/sequence, `binding`, `receipt`,
`release`. No list or truncation may hide older ownership. Both lookups remain
available after stop-grant expiry/revocation.

V2 bound host exit pins `runtime_sequence` plus the exact existing binding. Idle
exit pins `last_sequence` even when no binding is active. A delayed idle-N request
cannot retire idle-(N+1). Bound writes lock the preselected job chain then Runtime,
recheck the exact cursor and refuse on change; they never retarget under Runtime.
Purpose hashes cover `{schema,runtime_id,...exact_body}`, using
`vardr.worker-exit-report/2` or `vardr.worker-unbound-exit-report/2` respectively.
The unchanged four-key `vardr.worker-host-stop/1` ACK wraps this physical receipt:

```text
{schema:"vardr.worker-retirement/2", runtime_id, runtime_sha256, origin,
 runner_id, enrollment_id, runtime_sequence, last_sequence, binding,
 attempt_receipt, report_sha256, retired:true, receipt_sha256}
```

The final digest covers every preceding key. Idle sequence/binding/attempt receipt
are all null. A bound sequence equals `last_sequence`; its nested canonical v1 job
receipt remains unchanged. Physical retirement preserves an already completed,
failed or cancelled job. Only an unfinished attempt can enter the existing failed
result or observed-exit stop lane; there is no second receipt or success rewrite.

Original-key observation with explicit runtime ID/hash/sequence selects
`vardr.managed-claim-observation/3` and echoes all three fields. Existing `/1` and
`/2` shapes are unchanged. A claimed sequence observes its own history even when a
later sequence is active. Conflicting/orphan/partial history refuses. An untouched
unknown local intent may use final retirement only when `last_sequence` is below
its requested sequence, proving it was never issued; absence alone stays held.
Current original-key/enrollment authentication remains required. No observation
creates a claim/consume/release ACK, retry or refund.

## Immutable admission

An existing human-owner session registers a host-selected public `runtime_id`
UUID through `POST /managed/runtimes/{runtime_id}/register`. Local sessions retain
CSRF/Origin checks; API keys cannot register this reporting authority. Its body is:

```text
{enrollment_id, runner_id, origin, identity, capability_sha256, expires_in_seconds}
identity = {daemon_id, container_id, image_id, project, started_at, owner_nonce}
```

The container ID is full 64-digit lowercase hex, the image ID is `sha256:` plus
64-digit lowercase hex, and the fresh lifecycle-owner nonce is 64-digit lowercase
hex. `started_at` retains the Docker UTC RFC3339Nano string. `runtime_sha256` hashes
the original six-field identity using sorted compact ASCII JSON. Physical
incarnation uniqueness separately canonicalizes timestamp aliases to nine decimal
places without dropping nanoseconds. Runtime metadata, capability hash, nonce and
bound contract cannot be reused under another registration.

The host generates a separate random 256-bit secret represented as 64 lowercase
hex characters. Only its purpose hash reaches registration/server storage:

```text
SHA256(b"VardrSec.WorkerStop.v1\0" + secret.encode("ascii"))
```

The secret remains in the host's protected store outside container-accessible
paths. It never enters public admission, container environment, arguments, labels
or Runner journal. Host storage and direct daemon proof belong to the distribution.
Map cannot independently inspect the daemon; the owner-approved stop grant trusts
that host producer. A submitted observation hash is integrity metadata, not remote
attestation.

An explicit TTL of 60–604800 seconds is required independently of the work
approval's expiry. Exact registration replay preserves its original TTL, expiry,
identity and hash. `POST /managed/runtimes/{runtime_id}/revoke` takes an empty owner
session request and permanently disables new use of that grant.

Public admission contains exactly:

```text
{schema:"vardr.worker-admission/1", runtime_id, runtime_sha256,
 enrollment_id, runner_id, origin, capability_sha256, identity, expires_at}
```

## Claim, consumption and launch ordering

The existing managed claim accepts paired optional `runtime_id` and
`runtime_sha256`. With an explicitly injected runtime service, a trusted internal
claim hook associates the issued attempt with that runtime in the same transaction
as ownership, frozen case, contract, ordinal and budget allocation. A lost first
reply therefore retains a recoverable runtime association. Omitting the fields
preserves the existing native path; supplied runtime fields never fall back to it.

After the existing one-shot consumption acknowledgement,
`POST /jobs/{job_id}/managed/runtime-bind` takes the original owned control fields,
contract/attempt/fence/hash and runtime ID/hash. It confirms the exact pre-associated
tuple once while permission and admission are live. Its acknowledgement is:

```text
{schema:"vardr.worker-runtime-binding/1", origin, job_id, runner_id,
 contract_id, attempt_id, fence, contract_sha256,
 runtime_id, runtime_sha256, bound:true}
```

Runner must also verify its actual lifecycle-owner readiness/nonce through the
private channel and durably retain this acknowledgement before target launch.
Public metadata alone is insufficient readiness. Unknown claim, consumption or
confirmation replies grant no retry/re-execution right.

## Observed physical exit

Only the distinct `Authorization: VardrStop <64hex>` scheme authenticates the host
report/lookup routes. Existing execution and owner-session APIs do not accept it.

`POST /managed/runtimes/{runtime_id}/observed-exit` takes:

```text
{runtime_sha256, origin, job_id, runner_id, contract_id, attempt_id, fence,
 contract_sha256, finished_at, exit_code, observation_sha256}
```

The direct validated daemon adapter supplies these fields after matching the
retained incarnation and exact server binding. The server accepts no caller-selected
outcome, cause, old token or confirmation boolean. It fixes `failed/observed_exit`
and shares the native producer's serialized result/stop exclusion and terminal
reservation mutation. Its response wraps the canonical immutable managed-stop
receipt, or the existing result's failed completion, in `vardr.worker-host-stop/1`
with runtime ID/hash. A host report can never produce a successful completion.

An already bound attempt can retain this independently approved stop grant after
enrollment/API-key or work-approval revocation. The retained enrollment's owner,
key ID, principal, Runner and origin must still match; missing/rewritten identity
holds. Explicit runtime-grant revocation or TTL expiry blocks a new report.

Physical exit before a consumption acknowledgement leaves `consumed:false`.
The exact runtime is retired with a report marker and a failed stop receipt;
execution/job become terminal and capacity is released. Issuance, target and
duration allocations remain spent. Native reporting still requires its original
consumed, confirmed-stop right. Read-only observation recognizes this narrow
`observed_exit` case only with the retained exact retired-runtime/report proof;
it never invents a consumption acknowledgement or native handle.

If an uploaded `ManagedResult` has no terminal completion, the same authenticated
report atomically fails that existing receipt and retires the exact runtime. It
requires the retained consumed contract and uses the native failed-finish helper;
it creates no `ManagedStop`. The original result, artifact/case hashes, evidence,
candidates and spent allowances remain unchanged. Existing native terminal
completions cannot be replaced by a host report; use immutable lookup instead.
An identical accepted host report is idempotent while its grant remains active;
a changed report is refused. Read-only reconciliation keeps the canonical result
and failed completion without inventing a native process-termination assertion or
rewriting the Runner's original intended outcome.

## Physical exit before a runtime claim is bound

A durable local claim-send intent does not prove that its POST reached Map.
After direct stopped-incarnation proof, the host may send
`POST /managed/runtimes/{runtime_id}/observed-unbound-exit` using the same active
`VardrStop` capability and exactly:

```text
{runtime_sha256, finished_at, exit_code, observation_sha256}
```

This operation locks the runtime before the clock, as claim preparation does.
If claim already associated an attempt, retirement refuses and the exact bound
reporting lane is required. If retirement wins, its irreversible marker refuses
every later runtime-tagged claim. It changes no job, approval, receipt lane or
budget. A pending job can remain pending; this proves that incarnation is unbound,
not that another native invocation cannot claim the job.

The report digest has the distinct `vardr.worker-unbound-exit-report/1` purpose
and includes runtime ID/hash and all four submitted fields. The host response
wraps this canonical receipt in `vardr.worker-host-stop/1`:

```text
{schema:"vardr.worker-unbound-retirement/1", runtime_id, runtime_sha256,
 origin, runner_id, enrollment_id, report_sha256, bound:false, retired:true,
 receipt_sha256}
```

`receipt_sha256` hashes the canonical receipt without that hash field. Existing
schema 0039's retirement/report columns retain it without migration. Exact report
replay is idempotent while the grant is active; changed reports refuse. Lookup
retains the receipt after grant expiry/revocation, but those states cannot create
a retirement. Null binding without this retained receipt remains a hold.

For local audit, the existing original-key job observation accepts optional paired
`runtime_id`/`runtime_sha256`. Supplying both selects
`vardr.managed-claim-observation/2`, with the exact v1 fields and one additional
`runtime_retirement` receipt or null. Omission preserves the exact v1 response.
Existing ownership, active enrollment, original key, Runner/origin and
plan/case/association checks remain. The runtime must match the observed attempt,
including both associations being absent for an unbound receipt. Deleted keys,
revoked enrollment, unrelated attempts and partial request pairs refuse.

The worker must durably link the runtime ID/hash to the original run/job and
fingerprints in the same journal transaction as claim-send preparation. Only that
retained link and authenticated matching v2 receipt may retire local metadata as
not claimed by the retired runtime. Contract/consumption/PID/artifact/receipt or
active-ledger evidence prevents this path. Old unlinked intents stay held. No
control token, consumption acknowledgement, budget refund or retry right is made;
the original claim and runtime tombstones remain.

## Immutable reconciliation

`POST /managed/runtimes/{runtime_id}/receipt` takes only `{runtime_sha256}` under
the same stop-secret hash authentication. It returns:

```text
{schema:"vardr.worker-receipt-observation/1", runtime_id, runtime_sha256,
 binding:<immutable public attempt tuple or null>,
 receipt:<already terminal canonical stop/completion receipt or null>}
```

This exact observation remains available after grant expiry, revocation or
retirement. It exposes no live control state, execution token, case, approval,
credential or renewed permission. A missing receipt is no authority to repeat a
report or execution. Expired/revoked grants with no existing terminal receipt keep
their hold and require explicit owner-authorized recovery; no replacement or
authority repair is performed implicitly.

All runtime requests use HTTPS and strict identity-encoded JSON with the existing
8 KiB/three-second total body-read bounds. Replies are capped at 16 KiB and carry
`Cache-Control: no-store`; failures return fixed `managed_runtime_refused` details.
Only hashes and immutable metadata enter additive `0039managedruntime` storage;
rollback retains those records by refusing downgrade deletion.
