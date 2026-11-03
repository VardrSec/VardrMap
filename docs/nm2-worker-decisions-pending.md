# NM-2 worker decisions — pending review

Status: options and unresolved choices only. **No containment, bootstrap or lifecycle option is selected or implemented.**
Basis: the canonical `VardrSec_New_Moon_Roadmap.md`, read through Library, and later
owner instructions. The roadmap is approved direction, not implementation authority.

## Existing approved constraints

D02 requires bounded graceful then forced termination, accurate uncertainty and
partial evidence. D04/D08 require the shared contract, exact issuer/origin/job/
Runner binding and expiring/revocable local credential references. D07 retains
atomic concurrency/target/duration accounting without an unmeasured global RPS
claim. D11 prefers an operator-enabled, least-privilege Compose worker on Windows
Docker Desktop while preserving manual CLI and justified native fallback. D12
prohibits AI approval or permission escalation.

No Docker socket, privileged container, silent startup scanning, host credential
exposure, TLS weakening or uncontrolled execution fallback is authorized. Windows
checks may wait for Papachin; their gates remain open. Publication needs independent
review and required CI/security; migration review remains. Backup is waived.

Current baseline: Runner's controlled engine uses Windows Job Objects and refuses
Linux before managed claim. Compose's Runner is a manual tools service. Map's
issuer/services and read-only observation router are unregistered. Existing ADR
0016 removed startup workers; the D11 target requires an explicit reviewed amendment,
not restoration of removed daemon behavior by assumption.

## C — Container containment

| Candidate | Security consequences and evidence required |
| --- | --- |
| C1: delegated per-attempt cgroup v2 | Can offer a per-attempt process-membership boundary. Requires proven delegation/permissions, admission before tool creation, no tool access to controller interfaces, reliable empty-state confirmation, and owner-crash cleanup on Docker Desktop and supported Linux. Availability is unverified. |
| C2: one attempt per worker-container lifetime | Makes the container the proposed failure unit without giving Runner the Docker API. Requires a proven PID-1/supervisor/termination chain and restart handoff; container termination cannot selectively preserve other active jobs. Owner-crash, descendants, partial files and conservative accounting need tests. |
| C3: retain native Windows only | Preserves current behavior and documented exceptions. It does not satisfy the canonical Docker Desktop worker exit; changing that exit requires a separate scope decision. |

Kernel documentation specifies delegation boundaries and a subtree kill operation;
these do **not** establish that the required delegation is available in our images.
[Kernel cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html).
Docker's init option forwards signals/reaps processes; our inference is that this
alone is insufficient evidence for the required per-job containment contract.
[Compose service init](https://docs.docker.com/reference/compose-file/services/#init).

**Unresolved:** choose C1/C2 or explicitly change the target; name the authoritative
owner and failure unit; choose permitted controller access and local parallelism;
define measurable graceful/forced bounds and proof of termination versus uncertainty.
Process groups, PID existence, or an init flag alone are not accepted substitutes.

## B — Issuer, enrollment and secret bootstrap

| Candidate | Security consequences and evidence required |
| --- | --- |
| B1: explicit out-of-band provisioning | Populate existing enrollment/key-reference records and purpose-bound public anchors through a reviewed operator procedure. Smallest new application surface; needs reproducible rotation/revocation, ownership and recovery procedures. |
| B2: operator-only terminal management | Add a narrowly scoped create/revoke/configure interface using existing operator provenance. More code and audit obligations, but no public enrollment/signing API. Must not turn an ordinary API key or AI capability into approval. |

Approval private keys remain outside Map/workers/AI. Map's execution-signing key
must be distinct; Runner needs only purpose-bound verification material and its
enrolled API credential. Neither choice introduces a signing service, OAuth server
or automatic trust discovery. Container secrets may be granted per service, but
the host source and filesystem permissions still require review; this is not an
encrypted-storage assurance. [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).

**Unresolved:** choose B1/B2; identify the operator/provisioning authority, secret
source and access permissions; select key IDs, overlap/expiry/revocation behavior
and missing-key startup failure; define the container-local credential provider
without exporting the Windows keychain. Require exact configured API-base identity,
tenant/Runner/principal checks and human-signed receipt provenance throughout.
The existing `/backend` routing prefix is now preserved unchanged in synthetic
transport verification; no new origin namespace or trust-normalization rule is chosen.

## L — Operator lifecycle and recovery

The target candidate is a separate Compose worker, disabled by default, with an
explicit operator enable/start/disable path. Manual `jobs run` remains the baseline
and fallback, but does not by itself satisfy background-worker acceptance. No
Windows service or privileged host helper is required by the approved direction.

A Compose profile is packaging selection, not sufficient proof of consent: an
explicitly targeted service can start without manually enabling its profile.
Therefore an application enablement guard needs review and disabled-state tests.
[Compose profiles](https://docs.docker.com/compose/how-tos/profiles/).

**Unresolved:** choose the persisted enablement authority/state and who may change
it; select restart/backoff behavior after opt-in; define stop-new-claims, active-job
drain/cancel and grace expiry; specify side-effect-free health/readiness; define
operator-visible held jobs and original-principal receipt observation after restart.
Choose a total-call deadline policy: current transport bounds connect/read-idle
waits, not a dripping peer's total transfer time.
No stale PID signaling, capability reconstruction, automatic resend/refund or job
claim as a health probe is acceptable. A healthy process is not execution approval.

## Review handoff

The independent cloud work identified here is complete when the verification
checkpoint is preserved: actual two-role PostgreSQL HTTP-session tests and
verified TLS receipt flows behind the existing API prefix. These tests choose no
containment, provisioning or lifecycle option. The next implementation step needs
the unresolved choices above and a reviewed bounded test plan. Windows/Docker
Desktop, designated independent review, hosted CI/security, actual migration
comparison and NM-2 consolidation remain open. NM-3 has not begun.
