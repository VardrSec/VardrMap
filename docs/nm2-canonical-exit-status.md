# NM-2 canonical exit reconciliation

Status, 2026-11-05: NM-2 remains open; no integrated platform acceptance claimed.
NM-1 has closed at its original foundation/prototype and early-feasibility scope.
Existing NM-3 development and evidence are preserved and paused pending NM-2.

`VardrSec_New_Moon_Roadmap.md` is the canonical charter (decision baseline
2026-11-01). Later owner instructions authorize implementation and require NM-1
and NM-2 closeout before further NM-3 development. The owner explicitly approved
the bounded worker-only bootstrap and trusted-host stop-report design in
[Runner ADR 0043](https://github.com/VardrSec/VardrRunner/blob/ff3f4d81834acf1a46afc08312a1536c82a8fa19/docs/adr/0043-proposed-linux-worker-lifecycle-owner.md)
for implementation and testing. This does not waive acceptance, authorize release
or restart the previously blocked adversarial experiments.

The original exit requirements remain the denominator. Earlier local-row estimates
do not establish completion. A default-disabled integrated candidate now exists,
but **none of the ten clauses below has its complete current platform evidence**.
Two basic Desktop owner-readiness trials refused before admission, claim or target
traffic. The demonstrated Docker tmpfs/archive mismatch is being corrected with
a dedicated fresh metadata volume; it is not a passing worker demonstration.

| Clause | Canonical requirement | Current state and remaining work |
| --- | --- | --- |
| NM2-E01 | Queued Map job executes with approved worker running in Docker Desktop | **candidate implemented; acceptance open** — Explicit Map assembly, atomic runtime association, worker orchestration, native owner and separate Compose profile exist. Basic readiness proof refused; coupled queue execution and continuing worker availability remain unaccepted. |
| NM2-E02 | No execution when worker is disabled | **candidate implemented; acceptance open** — Default-off assembly/profile and public admission checks exist. Prepared-worker host control is being integrated. Demonstrate actual disabled and explicitly enabled states with independent target counts. |
| NM2-E03 | Unauthorized/expired queued jobs fail closed in Strict | **partial** — Shared validation, exact bindings, grants and explicit managed adapters are implemented. Demonstrate rejection through the actual worker/queue with no target effects. |
| NM2-E04 | Stop-work terminates active children within documented bounds | **partial** — Windows Job Objects and a reviewed worker-only PID-1 owner are implemented. Current native Windows, actual Desktop and supported Linux timing/termination evidence remain required; unit or socket fixtures do not certify containment. |
| NM2-E05 | Disconnection passes tests | **partial** — Monotonic leases, no fallback, timeout/dropped-reply tests and read-only reconciliation are locally exercised. New bounded transport adds explicit no-redirect/no-retry/size/strict-JSON behavior. Exercise the integrated worker under disconnect; transport connect/read-idle waits are not a total wall-clock transfer deadline. |
| NM2-E06 | Crash/restart passes tests | **partial** — Durable claim/result/stop intents and six fresh-process observation cases retain fences/files/PIDs without replay or reconstructed capability. Actual native owner-crash and worker restart need current environment verification. Current Windows/Papachin and container worker crash/restart checks; unknown containment remains held. |
| NM2-E07 | Duplicate claims pass tests | **partial** — Single-winner atomic claims, unique job/ordinal tombstones, one-shot consume/ACK and ambiguous-send no-replay checks pass local SQLite/PostgreSQL tests. Verify identical invariants in integrated production route and worker competition; do not add speculative distributed scheduling. |
| NM2-E08 | Revoked grants pass tests | **partial** — Engagement/origin-bound TTL/grant identity, revoke/expiry and final native launch writer checks exist; secrets stay local. Verify integrated container credential provider and current Windows path without host credential-store exposure. |
| NM2-E09 | Budget exhaustion passes tests | **partial** — Concurrency, represented-origin target attempts and allocated duration atomically reserve/charge without refunding unknown attempts. PostgreSQL role/race tests pass. Exercise actual worker exhaustion; retain precise accounting labels and no unmeasured global RPS claim. |
| NM2-E10 | Native fallback remains functional for documented exceptions | **partial** — Legacy/direct CLI compatibility tests remain green. New managed mode does not enable Linux controlled execution or controlled ffuf. Current native Windows execution and documented host/private/VPN exceptions require equivalent safety evidence; broad network/fresh-host certification belongs to its declared later gates. |

## Necessary bounded transport increment

An explicit `VardrMapClient.managed_post` provides one-shot HTTPS JSON with no
redirects or retries, fresh cookie-free sessions, explicit header authentication,
inherited proxy/CA/client-certificate configuration, strict finite JSON, and body
caps. Generic client behavior remains unchanged. Managed Map factories now have
an explicit default-off configuration loader; terminal enrollment and separate
human-signed approval remain prerequisites. See [development](development.md).

The current bounds are 1 MiB request and 256 KiB response; oversized evidence is refused, never split or replayed. Connect/read-idle timeouts are bounded, **not a total wall-clock transfer deadline**. A dripping peer can extend transport time; existing monotonic/signed managed permission ceilings must still prevent launch or renewal after expiry. This increment supplies no new execution right.

Tests use synthetic keys, mocked sessions and verified loopback TLS with real authentication, receipt flows, bad certificates, redirects, ambiguous claims, strict JSON and body-size negatives. They establish neither Docker Desktop execution nor public/VPN/fresh-host certification.

Linux control now requires a live connection to the reviewed native lifecycle
owner; a public admission document or environment flag cannot make it available.
The initial candidate is one attempt per incarnation. Sequential healthy work,
failure-window recovery and exact operator control remain implementation or
acceptance gates. No uncontrolled fallback, Docker socket, privileged mode or TLS
weakening is accepted.

Independent review, current Windows/Linux acceptance, final hosted CI/security,
actual migrated integration and consolidation remain open. The preserved NM-3
work resumes only after phase closeout. No publication, merge or release is authorized.

## Read-only observation adapter follow-up

The earlier isolated increment added an unregistered HTTP router factory for
existing receipt observation only. It supplies no execution right and closes no
canonical integrated worker exit clause. Explicit opt-in assembly and the bounded
worker candidate were added afterward; their acceptance remains outstanding.
See [ADR 0012](adr/0012-unregistered-observation-http.md).
