"""Unit tests for the pure policy evaluator.

Every deny reason gets a test that fails if the control is removed. These run
without a database or an HTTP client, which is the point of keeping policy.py
dependency-free — the decision that separates authorized testing from unlawful
intrusion deserves exhaustive coverage, and exhaustive coverage through
integration tests would be too slow to write.
"""
from datetime import datetime, timedelta, timezone

import pytest

import policy

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


def _input(**overrides):
    base = dict(
        engagement_status="active",
        engagement_type="pentest",
        target="api.acme.com",
        capability="httpx",
        now=NOW,
        stop_work=False,
        authorization=policy.AuthorizationSnapshot(status="active"),
        scope_rules=(policy.ScopeRule(value="acme.com"), policy.ScopeRule(value="*.acme.com")),
    )
    base.update(overrides)
    return policy.PolicyInput(**base)


# --------------------------------------------------------------------------- #
# Allow
# --------------------------------------------------------------------------- #

def test_allows_in_scope_target_under_active_authorization():
    decision = policy.evaluate(_input())
    assert decision.allowed
    assert decision.reason == policy.ALLOWED


def test_decision_is_truthy_for_allow_and_falsy_for_deny():
    assert policy.evaluate(_input())
    assert not policy.evaluate(_input(stop_work=True))


# --------------------------------------------------------------------------- #
# The six deny conditions required by the security model
# --------------------------------------------------------------------------- #

def test_denies_when_stop_work_is_engaged():
    d = policy.evaluate(_input(stop_work=True))
    assert not d.allowed and d.reason == policy.STOP_WORK_ACTIVE


def test_stop_work_beats_every_other_condition():
    """The emergency brake must not be defeatable by fixing something else."""
    d = policy.evaluate(
        _input(stop_work=True, engagement_status="closed", target="not-in-scope.test.com")
    )
    assert d.reason == policy.STOP_WORK_ACTIVE


@pytest.mark.parametrize("status", ["planned", "reporting", "closed", ""])
def test_denies_when_engagement_is_not_active(status):
    d = policy.evaluate(_input(engagement_status=status))
    assert not d.allowed and d.reason == policy.ENGAGEMENT_NOT_ACTIVE


def test_denies_when_non_bounty_engagement_has_no_authorization():
    d = policy.evaluate(_input(engagement_type="pentest", authorization=None))
    assert not d.allowed and d.reason == policy.AUTHORIZATION_MISSING


@pytest.mark.parametrize("status", ["draft", "pending", "suspended", "expired", "revoked", "closed"])
def test_denies_when_authorization_is_not_active(status):
    d = policy.evaluate(_input(authorization=policy.AuthorizationSnapshot(status=status)))
    assert not d.allowed and d.reason == policy.AUTHORIZATION_NOT_ACTIVE


def test_denies_before_the_window_opens():
    auth = policy.AuthorizationSnapshot(status="active", window_start=NOW + timedelta(days=1))
    d = policy.evaluate(_input(authorization=auth))
    assert not d.allowed and d.reason == policy.OUTSIDE_TESTING_WINDOW


def test_denies_after_the_window_closes():
    auth = policy.AuthorizationSnapshot(status="active", window_end=NOW - timedelta(seconds=1))
    d = policy.evaluate(_input(authorization=auth))
    assert not d.allowed and d.reason == policy.OUTSIDE_TESTING_WINDOW


def test_allows_inside_the_window():
    auth = policy.AuthorizationSnapshot(
        status="active",
        window_start=NOW - timedelta(days=1),
        window_end=NOW + timedelta(days=1),
    )
    assert policy.evaluate(_input(authorization=auth)).allowed


def test_naive_window_datetimes_are_treated_as_utc():
    """SQLite drops tzinfo; Postgres keeps it. The same row must decide the same."""
    auth = policy.AuthorizationSnapshot(
        status="active", window_end=datetime(2026, 8, 12, 11, 0)  # naive, one hour ago
    )
    d = policy.evaluate(_input(authorization=auth))
    assert not d.allowed and d.reason == policy.OUTSIDE_TESTING_WINDOW


def test_denies_a_capability_outside_the_permitted_set():
    auth = policy.AuthorizationSnapshot(
        status="active", permitted_capabilities=frozenset({"httpx"})
    )
    d = policy.evaluate(_input(authorization=auth, capability="nuclei"))
    assert not d.allowed and d.reason == policy.CAPABILITY_PROHIBITED


def test_empty_permitted_capabilities_means_no_restriction():
    auth = policy.AuthorizationSnapshot(status="active", permitted_capabilities=frozenset())
    assert policy.evaluate(_input(authorization=auth, capability="nuclei")).allowed


def test_denies_out_of_scope_target():
    d = policy.evaluate(_input(target="evil.example.com"))
    assert not d.allowed and d.reason == policy.TARGET_OUT_OF_SCOPE


def test_denies_when_no_scope_rules_exist():
    d = policy.evaluate(_input(scope_rules=()))
    assert not d.allowed and d.reason == policy.TARGET_OUT_OF_SCOPE


@pytest.mark.parametrize("target", ["", "   ", "not a host", "localhost", "://"])
def test_denies_unresolvable_target_as_ambiguous(target):
    d = policy.evaluate(_input(target=target))
    assert not d.allowed and d.reason == policy.SCOPE_AMBIGUOUS


# --------------------------------------------------------------------------- #
# Exclusions
# --------------------------------------------------------------------------- #

def test_exclusion_beats_a_matching_inclusion():
    """The invariant: an explicit carve-out is never overridden by a broader include."""
    rules = (
        policy.ScopeRule(value="*.acme.com"),
        policy.ScopeRule(value="prod.acme.com", excluded=True),
    )
    d = policy.evaluate(_input(target="prod.acme.com", scope_rules=rules))
    assert not d.allowed and d.reason == policy.TARGET_EXCLUDED


def test_exclusion_beats_inclusion_regardless_of_rule_order():
    rules = (
        policy.ScopeRule(value="prod.acme.com", excluded=True),
        policy.ScopeRule(value="*.acme.com"),
    )
    assert policy.evaluate(_input(target="prod.acme.com", scope_rules=rules)).reason == (
        policy.TARGET_EXCLUDED
    )


def test_exclusion_covers_subdomains_of_the_excluded_host():
    rules = (
        policy.ScopeRule(value="*.acme.com"),
        policy.ScopeRule(value="prod.acme.com", excluded=True),
    )
    d = policy.evaluate(_input(target="db.prod.acme.com", scope_rules=rules))
    assert not d.allowed and d.reason == policy.TARGET_EXCLUDED


def test_sibling_of_an_excluded_host_is_still_allowed():
    rules = (
        policy.ScopeRule(value="*.acme.com"),
        policy.ScopeRule(value="prod.acme.com", excluded=True),
    )
    assert policy.evaluate(_input(target="staging.acme.com", scope_rules=rules)).allowed


# --------------------------------------------------------------------------- #
# Target normalization and matching
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "target",
    [
        "api.acme.com",
        "API.ACME.COM",
        "https://api.acme.com",
        "https://api.acme.com/v1/users",
        "http://api.acme.com:8443/health",
        "api.acme.com.",
    ],
)
def test_equivalent_target_spellings_all_match_one_rule(target):
    assert policy.evaluate(_input(target=target)).allowed


def test_credentials_in_url_are_stripped_before_matching():
    """A userinfo segment must never participate in a scope comparison."""
    assert policy.evaluate(_input(target="https://user:pass@api.acme.com/x")).allowed


def test_lookalike_domain_does_not_match():
    """Substring matching would let notacme.com through. It must not."""
    d = policy.evaluate(_input(target="notacme.com"))
    assert not d.allowed and d.reason == policy.TARGET_OUT_OF_SCOPE


def test_apex_matches_a_bare_domain_rule():
    assert policy.evaluate(
        _input(target="acme.com", scope_rules=(policy.ScopeRule(value="acme.com"),))
    ).allowed


def test_wildcard_rule_covers_subdomains_but_not_the_apex():
    rules = (policy.ScopeRule(value="*.acme.com"),)
    assert policy.evaluate(_input(target="api.acme.com", scope_rules=rules)).allowed
    assert not policy.evaluate(_input(target="acme.com", scope_rules=rules)).allowed


# --------------------------------------------------------------------------- #
# Regressions — reported authorization bypasses
# --------------------------------------------------------------------------- #

def test_bare_domain_does_not_implicitly_authorize_subdomains():
    """Reported bypass: `acme.com` silently authorized every name beneath it.

    That is a default-allow. Writing one in-scope domain must not authorize
    `internal-admin.acme.com` — precisely the host an engagement most often
    means to exclude. Subdomain coverage requires an explicit wildcard.
    """
    rules = (policy.ScopeRule(value="acme.com"),)
    d = policy.evaluate(_input(target="internal-admin.acme.com", scope_rules=rules))
    assert not d.allowed and d.reason == policy.TARGET_OUT_OF_SCOPE


def test_path_rule_does_not_authorize_a_longer_sibling_segment():
    """Reported bypass: a `/v1/admin` rule authorized `/v1/administrator`.

    Prefix matching must stop at segment boundaries.
    """
    rules = (policy.ScopeRule(value="https://api.acme.com/v1/admin", kind="api"),)
    assert not policy.evaluate(
        _input(target="https://api.acme.com/v1/administrator", scope_rules=rules)
    ).allowed
    assert policy.evaluate(
        _input(target="https://api.acme.com/v1/admin/reset", scope_rules=rules)
    ).allowed
    assert policy.evaluate(
        _input(target="https://api.acme.com/v1/admin", scope_rules=rules)
    ).allowed


def test_url_rule_respects_scheme():
    """A rule for https must not authorize plaintext http on the same host."""
    rules = (policy.ScopeRule(value="https://api.acme.com/v1", kind="url"),)
    assert not policy.evaluate(
        _input(target="http://api.acme.com/v1", scope_rules=rules)
    ).allowed


def test_url_rule_respects_port():
    """Reported bypass: https://host:443 authorized http://host:8080.

    A different port is a different listener, frequently a different app.
    """
    rules = (policy.ScopeRule(value="https://api.acme.com:443/v1", kind="url"),)
    assert not policy.evaluate(
        _input(target="http://api.acme.com:8080/v1", scope_rules=rules)
    ).allowed
    assert policy.evaluate(
        _input(target="https://api.acme.com/v1", scope_rules=rules)
    ).allowed, "the scheme's default port must still match"


def test_exclusions_still_cover_subdomains_implicitly():
    """The asymmetry is deliberate — widening a deny is safe, widening an allow is not."""
    rules = (
        policy.ScopeRule(value="*.acme.com"),
        policy.ScopeRule(value="prod.acme.com", excluded=True),
    )
    d = policy.evaluate(_input(target="db.prod.acme.com", scope_rules=rules))
    assert not d.allowed and d.reason == policy.TARGET_EXCLUDED


def test_ip_target_matches_a_cidr_rule():
    rules = (policy.ScopeRule(value="10.0.0.0/24", kind="cidr"),)
    assert policy.evaluate(_input(target="10.0.0.7", scope_rules=rules)).allowed


def test_ip_outside_the_cidr_is_denied():
    rules = (policy.ScopeRule(value="10.0.0.0/24", kind="cidr"),)
    d = policy.evaluate(_input(target="10.0.1.7", scope_rules=rules))
    assert not d.allowed and d.reason == policy.TARGET_OUT_OF_SCOPE


def test_domain_rule_does_not_match_an_ip_target():
    d = policy.evaluate(_input(target="93.184.216.34"))
    assert not d.allowed and d.reason == policy.TARGET_OUT_OF_SCOPE


def test_api_route_rule_scopes_to_a_path_prefix():
    rules = (policy.ScopeRule(value="https://api.acme.com/v1", kind="api"),)
    assert policy.evaluate(_input(target="https://api.acme.com/v1/users", scope_rules=rules)).allowed
    assert not policy.evaluate(
        _input(target="https://api.acme.com/v2/users", scope_rules=rules)
    ).allowed


def test_api_route_exclusion_carves_out_one_path():
    rules = (
        policy.ScopeRule(value="*.acme.com"),
        policy.ScopeRule(value="https://api.acme.com/admin", kind="api", excluded=True),
    )
    assert policy.evaluate(_input(target="https://api.acme.com/users", scope_rules=rules)).allowed
    assert policy.evaluate(
        _input(target="https://api.acme.com/admin/reset", scope_rules=rules)
    ).reason == policy.TARGET_EXCLUDED


# --------------------------------------------------------------------------- #
# Bug bounty carve-out
# --------------------------------------------------------------------------- #

def test_bounty_engagement_needs_no_authorization_record():
    """The programme's published policy is the authority for bounty work."""
    assert policy.evaluate(_input(engagement_type="bug_bounty", authorization=None)).allowed


def test_bounty_engagement_still_enforces_scope():
    d = policy.evaluate(
        _input(engagement_type="bug_bounty", authorization=None, target="evil.example.com")
    )
    assert not d.allowed and d.reason == policy.TARGET_OUT_OF_SCOPE


def test_bounty_engagement_still_enforces_stop_work():
    d = policy.evaluate(_input(engagement_type="bug_bounty", authorization=None, stop_work=True))
    assert not d.allowed and d.reason == policy.STOP_WORK_ACTIVE


def test_bounty_engagement_still_enforces_engagement_status():
    d = policy.evaluate(
        _input(engagement_type="bug_bounty", authorization=None, engagement_status="closed")
    )
    assert not d.allowed and d.reason == policy.ENGAGEMENT_NOT_ACTIVE


@pytest.mark.parametrize("engagement_type", ["pentest", "red_team", "internal"])
def test_non_bounty_types_all_require_authorization(engagement_type):
    d = policy.evaluate(_input(engagement_type=engagement_type, authorization=None))
    assert not d.allowed and d.reason == policy.AUTHORIZATION_MISSING


# --------------------------------------------------------------------------- #
# Multi-target evaluation
# --------------------------------------------------------------------------- #

def test_all_targets_must_pass():
    d = policy.evaluate_all(_input(), ["api.acme.com", "www.acme.com"])
    assert d.allowed


def test_one_out_of_scope_target_denies_the_whole_job():
    """A job runs as a unit — partial authorization is not a meaningful state."""
    d = policy.evaluate_all(_input(), ["api.acme.com", "evil.example.com"])
    assert not d.allowed and d.reason == policy.TARGET_OUT_OF_SCOPE


def test_a_job_with_no_targets_passes_when_engagement_gates_pass():
    """Zero targets executes nothing, so refusing it would prevent nothing."""
    assert policy.evaluate_all(_input(), []).allowed


def test_a_job_with_no_targets_is_still_denied_by_stop_work():
    """Engagement gates apply even when nothing would run."""
    d = policy.evaluate_all(_input(stop_work=True), [])
    assert not d.allowed and d.reason == policy.STOP_WORK_ACTIVE


def test_a_job_with_no_targets_is_still_denied_without_authorization():
    d = policy.evaluate_all(_input(engagement_type="pentest", authorization=None), [])
    assert not d.allowed and d.reason == policy.AUTHORIZATION_MISSING
