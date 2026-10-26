# ADR 0003: Component readiness belongs to Map; diagnostics belong to Runner

Status: Accepted, 2026-10-25

## Decision

Preserve the agreed component boundaries. The future VardrSec distribution owns
Compose lifecycle and compatible releases. Runner owns installation diagnostics
and explicitly invoked execution. Map owns its API/data readiness interface and
eventual presentation of status; Gate remains the authorization-testing engine.

Add `GET /ready` with a versioned, value-free contract, UTC observation time and
no-store response. A successful database read plus exact equality with the single
packaged Alembic head produces 200; unavailable or different state produces 503.
Read only revision markers; never run or stamp migrations. `/health` is unchanged.

Use an independent unpooled connection to avoid consuming the application pool.
PostgreSQL probes retain TLS settings and enforce read-only sessions and bounded
connection/statement waits. Do not return connection details, revisions or error
text. Keep existing global request rate limiting.

The minimal interface is public: database-backed runner-key authentication cannot
be a prerequisite for observing a database outage. No user or tenant information
is exposed, and all protected API routes retain their existing requirements.

## Consequences

Runner opts into the new contract; old doctor behavior remains supported. A 404,
malformed response or unsupported contract cannot establish platform readiness.
No Docker socket, shared database connection, background worker, UI feature,
container publication or new deployment is introduced.

The marker is not an independent schema-integrity audit. A manually stamped but
damaged schema can still need repair; end-to-end acceptance remains necessary.
Readiness does not prove UI availability, credential validity, tool installation,
privacy, backups or successful authorization tests. Development create-all
databases without migration history are intentionally not migration-ready.
