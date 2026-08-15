# ADR 0001 — Central policy engine for execution authorization

**Status:** Accepted · **Date:** 2026-08-12 · **Supersedes:** none

## Context

`Authorization` has stored `window_start`, `window_end`, and `status` since
v0.22. Grepping `jobs.py`, `scans.py`, `runner.py`, and `schedules.py` for
`Authorization` returned nothing. The platform recorded the authority to test
and then ignored it.

For a product whose premise is *authorized* security testing, that is a
default-allow: a scan could be dispatched against a client whose authorization
was expired, suspended, or revoked, and the only trace would be a record
asserting it should not have happened.

## Decision

Centralize the decision in `backend/policy.py`, a pure module with no
SQLAlchemy, FastAPI, or I/O dependency. Callers assemble a `PolicyInput` from
ORM rows; it returns a `PolicyDecision` carrying `allowed` and a stable reason
code. `backend/enforcement.py` is the thin DB-aware adapter that gathers facts,
records denials, and raises HTTP 403.

### Why pure

A policy exercisable only through an HTTP request will not be exhaustively
tested. This one guards the difference between authorized testing and unlawful
intrusion, so it gets 59 unit tests that run in under a second, plus 25
integration tests proving it is actually wired in.

### Enforcement at two points

Evaluated at **job creation** and again at **job claim**. A single check at
creation would make the testing window advisory — a job queued while the window
was open and claimed an hour after it closed would still run. The claim-time
check is what makes the control real, and it has a dedicated test.

### Exclusions beat inclusions, unconditionally

Not "most specific wins". An operator who wrote an exclusion meant it, and a
broad wildcard include must never silently re-admit a carved-out host.

### Ambiguity denies

A target that cannot be normalized to a host, IP, or URL is refused rather than
permitted, and the refusal is audited.

## The empty-target question

The first implementation denied a job that resolved to zero targets, reasoning
that "no scope" should not execute. That broke 41 existing tests, all on
engagements with no scope configured.

The tests were right and the design was wrong. **A job with zero targets
executes nothing, so refusing it prevents nothing** — it is a usability
obstruction, not a security control. The engagement-level gates (stop-work,
status, authorization, window, capability) still apply to a zero-target job,
so the brake still works; only the per-target scope check is skipped when there
is nothing to check.

The real enforcement value is `target_source="recon"`, where discovered hosts
may fall outside a scope that was narrowed after recon ran. That case has its
own test.

## Bug bounty carve-out

`engagement_type == "bug_bounty"` skips the authorization-record requirement —
the programme's published policy is the authority, and there is no counterparty
to sign an SOW. Scope, exclusions, stop-work, and engagement status still apply.
This is the only carve-out. Without it the product would be unusable for bounty
work, which remains a first-class engagement type.

## Consequences

**Breaking.** `pentest`, `red_team`, and `internal` engagements now require an
active authorization record before any job dispatches. Existing `bug_bounty`
engagements are unaffected — the default `engagement_type` is `bug_bounty` and
the default `engagement_status` is `active`.

Denials are audited with a reason code, so a refused execution is visible rather
than merely blocked. `audit_logs.program_id` gains an index for that query.

## Alternatives rejected

**Enforce in a FastAPI dependency.** Cleaner-looking, but the decision would
only be reachable through a request, and claim-time enforcement needs the job
row rather than the path parameters.

**Enforce only at claim.** Fewer call sites, but a job that can never run should
not sit in the queue looking pending.

**Separate `ScopeRule` / `ScopeTarget` / `Exclusion` tables.** `scope_items`
already discriminates in/out with a `kind`. Three tables where one suffices is a
speculative abstraction, and splitting them would fragment existing data.
