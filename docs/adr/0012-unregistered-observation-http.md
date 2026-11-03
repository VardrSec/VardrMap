# ADR 0012 — Unregistered read-only managed observation HTTP adapter

Status: isolated prerequisite; production registration and canonical worker exit open.

## Decision

Provide `managed_observation_http.build_observation_router(service)` as an explicit
factory around the existing `Observations.inspect` service. It constructs no
issuer, signing key, enrollment, configuration or worker. `main.py` neither imports
nor registers the router. Synthetic apps alone call the factory.

Reserve `POST /jobs/{job_id}/managed/observation` for the existing v1 observation
shape: origin, Runner UUID and plan/case/association SHA-256 fingerprints. Require
HTTPS in the ASGI scope and the original actual enrolled API principal. Reuse
existing membership, enrollment, approval and retained receipt binding checks.
Preserve 401/403/404 distinctions from the underlying authentication/access layer;
fixed generic failures never echo request bodies, headers or error details.

The adapter exposes no claim, registration, signing, current permission, consume,
result submission, finish or stop mutation. It cannot produce an execution
capability. Observation does not renew leases, release reservations, refund counts,
create evidence or change terminal state. Existing auth/clock telemetry retains
its behavior. Absence remains a snapshot, never permission to retry.

Read at most 8 KiB of uncompressed JSON within a three-second total body-read wait.
Check declared and actual length, then use the shared strict duplicate/depth/finite
JSON decoder and exact typed request fields. Reject extra token/budget/approval
fields. Bound the serialized reply at 16 KiB. Return `Cache-Control: no-store` for
successful replies and handled failures. The body-read bound is not an overall DB
or network operation deadline. Existing signed/monotonic execution limits remain
separate and unchanged.

Call the synchronous service in the existing Starlette threadpool with the
request-scoped SQL session. No new server, async DB layer, shared service or
background task is introduced. Unexpected service failures become generic 503
responses, preserving fail-closed observation rather than exposing details.

## Verification and activation limits

Disposable ASGI tests cover actual enrolled-key authentication, membership,
revocation/deletion, exact fingerprints, absence and retained result/stop receipts,
no business-state mutation, no capability fields, body limits, timeout/disconnect,
fixed errors and explicit absence from the production OpenAPI route table. Verified
loopback TLS runs both receipt flows using Runner's existing bounded managed JSON
method against this factory's real adapter. Synthetic trust never becomes live trust.

Future production registration must verify existing TLS/proxy/auth deployment
configuration and supply the service through an explicitly reviewed configuration
boundary. Stateful issuer routes still require approved key/bootstrap wiring.
Controlled Linux/container execution and operator worker lifecycle remain absent;
no uncontrolled or privileged fallback is enabled. Windows/Papachin, independent
review, hosted CI/security, migration comparison and consolidation remain open.
Backup is waived. No NM-3 work, publication, merge, deployment or acceptance.
