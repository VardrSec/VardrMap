"""Central authorization and scope evaluation. Deny by default.

This module decides one question: *may this capability run against this target,
for this engagement, right now?* It is the only place that question is answered,
so the answer is testable without a database, a request, or a framework.

Deliberately pure. Callers assemble a `PolicyInput` from ORM objects and pass it
in; nothing here imports SQLAlchemy or FastAPI. A policy that can only be
exercised through an HTTP request is a policy that will not be exhaustively
tested, and this one guards the difference between authorized testing and
unlawful intrusion.

Two invariants drive the design:

1. **Exclusions beat inclusions, always.** Not "most specific wins" — an
   operator who wrote an exclusion meant it, and a wildcard include must never
   silently re-admit a host that was explicitly carved out.
2. **Ambiguity denies.** A target that cannot be resolved to a decision is
   refused, not permitted. Every deny carries a stable reason code so the
   audit trail records *why*, not merely *that*.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

# Stable reason codes. These reach the audit log and API clients, so treat them
# as a public contract: add freely, rename never.
ALLOWED = "allowed"
ENGAGEMENT_NOT_ACTIVE = "engagement_not_active"
STOP_WORK_ACTIVE = "stop_work_active"
AUTHORIZATION_MISSING = "authorization_missing"
AUTHORIZATION_NOT_ACTIVE = "authorization_not_active"
OUTSIDE_TESTING_WINDOW = "outside_testing_window"
CAPABILITY_PROHIBITED = "capability_prohibited"
TARGET_EXCLUDED = "target_excluded"
TARGET_OUT_OF_SCOPE = "target_out_of_scope"
SCOPE_AMBIGUOUS = "scope_ambiguous"

# Bug bounty engagements are authorized by the programme's published policy, not
# by a signed document we hold. Requiring an authorization record for them would
# make the product unusable for bounty work. Every other control still applies.
SELF_AUTHORIZING_TYPES = frozenset({"bug_bounty"})

ACTIVE_ENGAGEMENT_STATUS = "active"
ACTIVE_AUTHORIZATION_STATUS = "active"


@dataclass(frozen=True)
class ScopeRule:
    """One in-scope or out-of-scope rule. Mirrors a `scope_items` row."""

    value: str
    kind: str = "domain"
    excluded: bool = False


@dataclass(frozen=True)
class AuthorizationSnapshot:
    """The permission-to-test record, reduced to what the decision needs."""

    status: str
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    # Empty means "no restriction stated". A populated list is an allow-list.
    permitted_capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PolicyInput:
    engagement_status: str
    engagement_type: str
    target: str
    capability: str
    now: datetime
    stop_work: bool = False
    authorization: Optional[AuthorizationSnapshot] = None
    scope_rules: tuple[ScopeRule, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    detail: str = ""

    def __bool__(self) -> bool:  # `if decision:` reads naturally at call sites
        return self.allowed


def _as_utc(value: datetime) -> datetime:
    """Treat a naive datetime as UTC.

    SQLite round-trips datetimes without tzinfo while Postgres preserves it, so
    the same row compares differently depending on the backend. Normalising here
    keeps a testing window from silently evaluating as open on one and closed on
    the other.
    """
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def normalize_target(target: str) -> tuple[str, str]:
    """Reduce a target to (kind, comparable form).

    Returns `("", "")` when the target cannot be classified, which the evaluator
    treats as ambiguous and therefore denied.

    `https://API.Acme.com:8443/v1/users` and `api.acme.com` both reduce to the
    host `api.acme.com`, so a scope rule written either way matches both.
    """
    raw = (target or "").strip()
    if not raw:
        return "", ""

    remainder = raw
    if "://" in remainder:
        remainder = remainder.split("://", 1)[1]
    # Strip credentials — they must never participate in a scope comparison.
    if "@" in remainder.split("/", 1)[0]:
        remainder = remainder.split("@", 1)[1]
    host = remainder.split("/", 1)[0]

    # Bracketed IPv6 literal, optionally with a port.
    if host.startswith("["):
        closing = host.find("]")
        if closing == -1:
            return "", ""
        host = host[1:closing]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]

    host = host.rstrip(".").lower()
    if not host:
        return "", ""

    try:
        ipaddress.ip_address(host)
        return "ip", host
    except ValueError:
        pass

    # A hostname needs a dot and no whitespace; anything else we cannot classify.
    if " " in host or "." not in host:
        return "", ""
    return "domain", host


def _host_matches(rule_value: str, host: str) -> bool:
    """Domain rule matching, including implicit subdomain coverage.

    `acme.com` covers `api.acme.com`; `*.acme.com` covers subdomains but not the
    apex. Substring comparison is never used — `notacme.com` must not match
    `acme.com`.
    """
    rule = rule_value.strip().rstrip(".").lower()
    if not rule:
        return False
    if rule.startswith("*."):
        suffix = rule[2:]
        return host.endswith("." + suffix)
    if host == rule:
        return True
    return host.endswith("." + rule)


def _rule_matches(rule: ScopeRule, kind: str, value: str, raw_target: str) -> bool:
    rule_value = rule.value.strip().lower()
    if not rule_value:
        return False

    if rule.kind == "cidr":
        if kind != "ip":
            return False
        try:
            return ipaddress.ip_address(value) in ipaddress.ip_network(rule_value, strict=False)
        except ValueError:
            return False

    if rule.kind in ("url", "api"):
        # Path-bearing rules compare on the normalized full target, so
        # /v1/admin can be excluded without excluding the whole host.
        _, rule_host = normalize_target(rule_value)
        if rule_host and rule_host != value:
            return False
        rule_path = _path_of(rule_value)
        if not rule_path:
            return True
        return _path_of(raw_target).startswith(rule_path)

    if kind == "ip":
        # A bare IP rule must match exactly; domain semantics do not apply.
        return rule_value == value
    return _host_matches(rule_value, value)


def _path_of(target: str) -> str:
    remainder = target
    if "://" in remainder:
        remainder = remainder.split("://", 1)[1]
    if "/" not in remainder:
        return ""
    return "/" + remainder.split("/", 1)[1].split("?", 1)[0].rstrip("/").lower()


def evaluate_engagement(candidate: PolicyInput) -> PolicyDecision:
    """Check the gates that do not depend on a target.

    Stop-work, engagement status, authorization validity, testing window, and
    permitted capability apply to the engagement as a whole. They are evaluated
    once per job rather than once per target, and they apply even when a job
    resolves to no targets at all.
    """
    if candidate.stop_work:
        return PolicyDecision(False, STOP_WORK_ACTIVE, "Stop-work is engaged for this engagement.")

    if candidate.engagement_status != ACTIVE_ENGAGEMENT_STATUS:
        return PolicyDecision(
            False,
            ENGAGEMENT_NOT_ACTIVE,
            f"Engagement status is '{candidate.engagement_status}', not 'active'.",
        )

    auth = candidate.authorization
    self_authorizing = candidate.engagement_type in SELF_AUTHORIZING_TYPES

    if auth is None:
        if not self_authorizing:
            return PolicyDecision(
                False,
                AUTHORIZATION_MISSING,
                f"A '{candidate.engagement_type}' engagement requires an authorization record.",
            )
    else:
        if auth.status != ACTIVE_AUTHORIZATION_STATUS:
            return PolicyDecision(
                False,
                AUTHORIZATION_NOT_ACTIVE,
                f"Authorization status is '{auth.status}', not 'active'.",
            )

        now = _as_utc(candidate.now)
        if auth.window_start and now < _as_utc(auth.window_start):
            return PolicyDecision(
                False, OUTSIDE_TESTING_WINDOW, "The testing window has not opened yet."
            )
        if auth.window_end and now > _as_utc(auth.window_end):
            return PolicyDecision(
                False, OUTSIDE_TESTING_WINDOW, "The testing window has closed."
            )

        if auth.permitted_capabilities and candidate.capability not in auth.permitted_capabilities:
            return PolicyDecision(
                False,
                CAPABILITY_PROHIBITED,
                f"Capability '{candidate.capability}' is not permitted by this authorization.",
            )

    return PolicyDecision(True, ALLOWED, "Engagement-level checks passed.")


def evaluate(candidate: PolicyInput) -> PolicyDecision:
    """Decide whether execution may proceed against `candidate.target`.

    Order matters: the first failing condition is the reason reported, and the
    checks run cheapest-and-most-absolute first. Stop-work precedes everything
    because it is the emergency brake — if it is engaged, why the target is out
    of scope is not the interesting fact.
    """
    gate = evaluate_engagement(candidate)
    if not gate.allowed:
        return gate

    kind, value = normalize_target(candidate.target)
    if not kind:
        return PolicyDecision(
            False,
            SCOPE_AMBIGUOUS,
            f"Target '{candidate.target}' could not be resolved to a host, IP, or URL.",
        )

    # Exclusions first and unconditionally — an explicit carve-out is never
    # overridden by a broader include.
    for rule in candidate.scope_rules:
        if rule.excluded and _rule_matches(rule, kind, value, candidate.target):
            return PolicyDecision(
                False, TARGET_EXCLUDED, f"Target matches exclusion '{rule.value}'."
            )

    for rule in candidate.scope_rules:
        if not rule.excluded and _rule_matches(rule, kind, value, candidate.target):
            return PolicyDecision(True, ALLOWED, f"Target matches in-scope rule '{rule.value}'.")

    return PolicyDecision(
        False, TARGET_OUT_OF_SCOPE, "No in-scope rule matches this target."
    )


def evaluate_all(candidate: PolicyInput, targets: Iterable[str]) -> PolicyDecision:
    """Allow only if the engagement gates pass and every target is in scope.

    A job carries many targets and executes as a unit, so partial authorization
    is not a meaningful state — running it would test the out-of-scope host too.

    An empty target list is *not* a denial. A job that resolves to no targets
    executes nothing, so refusing it prevents nothing; it would only break
    ordinary use of an engagement whose scope has not been filled in yet. The
    engagement gates above still apply, so a zero-target job is still refused
    when stop-work is engaged or authorization has lapsed.
    """
    gate = evaluate_engagement(candidate)
    if not gate.allowed:
        return gate

    for target in targets:
        decision = evaluate(
            PolicyInput(
                engagement_status=candidate.engagement_status,
                engagement_type=candidate.engagement_type,
                target=target,
                capability=candidate.capability,
                now=candidate.now,
                stop_work=candidate.stop_work,
                authorization=candidate.authorization,
                scope_rules=candidate.scope_rules,
            )
        )
        if not decision.allowed:
            return decision
    return PolicyDecision(True, ALLOWED, "All targets are in scope.")
