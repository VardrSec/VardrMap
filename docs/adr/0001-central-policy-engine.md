# ADR 0001 — Central policy engine for execution authorization

**Status:** Accepted, amended v0.29.0 · **Date:** 2026-08-12 · **Supersedes:** none

> **Amendment (v0.29.0) — enforcement is now advisory.** The decision to
> centralize evaluation in a pure module stands and is unchanged; what changed is
> what the platform does with the result. Findings are returned to the caller as
> warnings and the job runs; only stop-work still refuses. Rationale in
> § Amendment at the end of this document.

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

## Amendment (v0.29.0) — advisory, not enforcing

The original decision made execution default-deny. That is reversed: findings
are now warnings, and the job runs.

**Why.** Enforcing scope means the platform interrupts paid work whenever its
reading of a rule disagrees with the operator's. Scope in the field is messier
than any rule set — verbal expansions mid-engagement, hosts that appear
overnight, ranges that shift — and v0.28.0 demonstrated the failure mode
concretely: tightening subdomain matching silently started denying jobs on
engagements that had been running fine. Being wrong in that direction costs the
operator an engagement; being wrong the other way costs them a warning they chose
to ignore.

The broader principle: this is a tool, and the tools it sits alongside do not
police their users. Burp will proxy any host you point it at; nmap will scan any
range you give it. Responsibility for staying inside scope belongs to the
operator, and a platform that claims to enforce it takes on a liability it cannot
actually discharge — a missed case reads as a guarantee that failed.

**What is kept.** Everything structural. `policy.py` is unchanged: same pure
module, same reason codes, same test suite. `enforcement.py` still gathers ORM
facts, but `check()` returns the decision instead of raising. Reason codes remain
a public contract, so a caller that wants a warning to be fatal can branch on it.

**The exception.** `stop_work_active` still returns `403`. It is not a judgement
about scope — it is the operator's own halt switch, and a brake that can be
ignored is not a brake.

**Not audited.** Warnings are no longer written to `audit_logs`. A scope finding
is advice to the operator, not a security event filed against them. Stop-work
engage/release remains audited.
