# Managed runtime admission and host stop receipts

This is the bounded ADR 0043 implementation protocol. It is disabled by default
and requires explicit worker configuration, an existing issuer, operator public
trust, a separate Map contract-signing key and an existing Runner enrollment.
Protocol tests do not establish Docker termination or platform acceptance.

The first incarnation supports one issued attempt. Sequential attempts in the same
container need a later reviewed binding/history and descendant-drain increment;
this prototype does not complete that worker requirement.

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
