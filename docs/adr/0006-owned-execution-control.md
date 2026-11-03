# ADR 0006 — Owned manual execution control

Status: local NM-2 increment for review; not deployed.

Keep legacy manual execution compatible. A claim body explicitly opts into an
attempt-bound cancellation protocol; it does not approve execution, migrate an
engagement to Strict or enable a worker. The new additive `job_executions` table
binds the job, exact configured Map URL, Runner UUID, authenticated API-key digest
and hash of a random per-attempt capability. The capability is returned only on
claim and never persisted in plaintext. No renewal, completion or ownership
fallback is allowed for an expired/uncertain attempt.

Lease duration is ten seconds. Stop-work blocks claims and records sticky cancel
requests atomically; releasing it does not revive existing attempts. A controlled
job stays running until its owner acknowledges termination or completion. Missing
acknowledgement is uncertainty, not confirmed cancellation. Legacy PATCH failure
requests cancellation on controlled jobs; it cannot forge done. Legacy jobs retain
their existing status contract. No evidence or Gate case hashes are changed.

All mutations serialize in engagement → job → execution order; stop-work takes
the engagement before changing its execution records. PostgreSQL race tests are
required in addition to SQLite tests. A terminal race may preserve completion
which committed first, or a cancellation request which committed first; it must
never lose the stop through deadlock or mark active work as already cancelled.

Controllers require current API-key authentication, engagement write access and
all per-attempt bindings. Keys for other users, other keys belonging to the same
user, wrong jobs/origins/Runners and invalid capabilities cannot renew or finalize.
The API is outbound-polled by an explicitly invoked Runner, not a pushed command
channel. The URL binding supplements authenticated TLS; it does not authenticate a
server independently. No v1 issuer/enrollment or managed approval API is added.

Deploy the matching migration/endpoints before publishing a dependent Runner.
This local increment changes no deployment or pins. For code rollback, retain
control rows and do not restart/reclaim uncertain attempts through a legacy client.
The migration refuses destructive downgrade; removing a fence is not rollback.
No existing engagement or retained database is migrated during development.

Whole NM-2 still requires managed signed authorization, launch-time credential
grant revalidation, atomic engagement budgets, tested connectivity/restart policy,
Linux/Docker execution proof and the separately opted-in least-privilege worker.
