"""`GET /engagements` must cost a constant number of queries, not a per-row one.

The list endpoint used to call `serialize_engagement` in a loop, and each call
issued six COUNTs plus two GROUP BYs and lazily loaded scope items and import
records. Twenty engagements meant well over a hundred round trips to render one
page.

The guard here is a ratio, not an absolute: adding one engagement must not add
queries. An absolute budget would break on unrelated refactors and get raised
until it meant nothing.
"""
from sqlalchemy import event

from db import SessionLocal
from models import (
    Engagement,
    EngagementMember,
    Finding,
    Organization,
    OrganizationMember,
    ReconItem,
    Report,
    ScopeItem,
)

# The second user in conftest. Everything below views the list as *them*, because
# the owner takes a short-circuit that hides per-engagement role lookups.
OTHER = "gh_user2"


class _QueryCounter:
    """Count SQL statements issued against the test engine inside the block."""

    def __init__(self):
        self.statements: list[str] = []

    def __enter__(self):
        from tests.conftest import _engine

        self._engine = _engine

        def _before(conn, cursor, statement, params, context, executemany):
            self.statements.append(statement)

        self._handler = _before
        event.listen(self._engine, "before_cursor_execute", self._handler)
        return self

    def __exit__(self, *exc):
        event.remove(self._engine, "before_cursor_execute", self._handler)
        return False

    def __len__(self):
        return len(self.statements)


def _seed(pid: str, findings: int = 3) -> None:
    """Give an engagement enough children that lazy loads would show up."""
    db = SessionLocal()
    try:
        for i in range(findings):
            db.add(Finding(program_id=pid, title=f"f{i}", severity="high", status="new"))
        db.add(ReconItem(program_id=pid, source="httpx", host=f"h-{pid[:6]}.test"))
        db.add(Report(program_id=pid, title="r"))
        db.add(ScopeItem(program_id=pid, scope_type="in", value=f"{pid[:6]}.test", kind="domain"))
        db.commit()
    finally:
        db.close()


def _make_engagement(client, headers, name: str) -> str:
    pid = client.post("/programs", json={"name": name}, headers=headers).json()["id"]
    _seed(pid)
    return pid


def test_engagement_list_query_count_does_not_grow_per_engagement(client, auth_headers):
    """One engagement vs. four must cost the same number of queries."""
    first = _make_engagement(client, auth_headers, "Q-count 1")
    try:
        with _QueryCounter() as one:
            res = client.get("/programs", headers=auth_headers)
            assert res.status_code == 200
        baseline = len(one)

        extra = [_make_engagement(client, auth_headers, f"Q-count {i}") for i in range(2, 5)]
        try:
            with _QueryCounter() as many:
                res = client.get("/programs", headers=auth_headers)
                assert res.status_code == 200
                assert len(res.json()["engagements"]) >= 4
            grown = len(many)

            assert grown <= baseline, (
                f"Serializing 4 engagements issued {grown} queries where 1 issued "
                f"{baseline}. The list endpoint must batch its aggregates — see "
                f"serialize_engagements. Per-engagement growth is the N+1 this "
                f"test exists to catch."
            )
        finally:
            for pid in extra:
                client.delete(f"/programs/{pid}", headers=auth_headers)
    finally:
        client.delete(f"/programs/{first}", headers=auth_headers)


def test_engagement_list_stays_correct_when_batched(client, auth_headers):
    """Batching must not change the numbers it reports."""
    pid = _make_engagement(client, auth_headers, "Q-count correctness")
    try:
        listed = client.get("/programs", headers=auth_headers).json()["engagements"]
        item = next(e for e in listed if e["id"] == pid)

        assert item["findings_count"] == 3
        assert item["findings_by_severity"]["high"] == 3
        assert item["findings_by_status"]["new"] == 3
        assert item["recon_count"] == 1
        assert item["reports_count"] == 1
        assert len(item["scope"]["in"]) == 1

        # The detail endpoint delegates to the same code path, so it must agree.
        detail = client.get(f"/programs/{pid}", headers=auth_headers).json()
        for key in (
            "findings_count", "findings_by_severity", "findings_by_status",
            "recon_count", "reports_count", "scans_count", "services_count",
            "manual_tests_count", "my_role",
        ):
            assert detail[key] == item[key], f"list and detail disagree on {key!r}"
    finally:
        client.delete(f"/programs/{pid}", headers=auth_headers)


def test_counts_are_not_cross_contaminated_between_engagements(client, auth_headers):
    """A grouped query returns rows for many engagements at once — each must get
    only its own totals."""
    a = _make_engagement(client, auth_headers, "Q-count A")
    b = client.post("/programs", json={"name": "Q-count B"}, headers=auth_headers).json()["id"]
    try:
        listed = client.get("/programs", headers=auth_headers).json()["engagements"]
        item_a = next(e for e in listed if e["id"] == a)
        item_b = next(e for e in listed if e["id"] == b)

        assert item_a["findings_count"] == 3
        assert item_b["findings_count"] == 0, "an unseeded engagement must report zero"
        assert item_b["findings_by_severity"]["high"] == 0
        assert item_b["scope"]["in"] == []
    finally:
        client.delete(f"/programs/{a}", headers=auth_headers)
        client.delete(f"/programs/{b}", headers=auth_headers)


def test_empty_list_is_cheap_and_valid(client, other_headers):
    """A user with no engagements must not trip the batch path."""
    with _QueryCounter() as counter:
        res = client.get("/programs", headers=other_headers)
    assert res.status_code == 200
    assert res.json()["engagements"] == []
    assert len(counter) < 10, "an empty list should not issue aggregate queries"


# --------------------------------------------------------------------------- #
# Non-owner callers — the path ownership short-circuits past
# --------------------------------------------------------------------------- #
#
# `engagement_access` returns "owner" before issuing any query, so a caller who
# owns every engagement never exercises role resolution. The tests above use
# exactly such a caller, which is why they could not catch a per-engagement role
# lookup. These view the same lists as a non-owner.


def _invite(pid: str, github_id: str = OTHER, role: str = "member") -> None:
    db = SessionLocal()
    try:
        db.add(EngagementMember(
            program_id=pid,
            owner_github_id="gh_user1",
            member_github_id=github_id,
            role=role,
        ))
        db.commit()
    finally:
        db.close()


def _put_in_org(pids: list[str], github_id: str = OTHER, role: str = "member") -> str:
    """Attach engagements to a shared org the given user belongs to."""
    db = SessionLocal()
    try:
        org = Organization(name="Query Count Org", personal_for_github_id="")
        db.add(org)
        db.flush()
        db.add(OrganizationMember(org_id=org.id, github_id=github_id, role=role))
        db.query(Engagement).filter(Engagement.id.in_(pids)).update(
            {"org_id": org.id}, synchronize_session=False
        )
        db.commit()
        return org.id
    finally:
        db.close()


def _count_for(client, headers, expected_visible: int) -> int:
    with _QueryCounter() as counter:
        res = client.get("/programs", headers=headers)
        assert res.status_code == 200
        assert len(res.json()["engagements"]) == expected_visible, (
            f"expected {expected_visible} visible engagements, "
            f"got {len(res.json()['engagements'])}"
        )
    return len(counter)


def test_invited_member_list_query_count_is_constant(client, auth_headers, other_headers):
    """A direct invitation is resolved with one query for the page, not per row."""
    first = _make_engagement(client, auth_headers, "Invited 1")
    _invite(first)
    try:
        baseline = _count_for(client, other_headers, 1)

        extra = []
        for i in range(2, 5):
            pid = _make_engagement(client, auth_headers, f"Invited {i}")
            _invite(pid)
            extra.append(pid)
        try:
            grown = _count_for(client, other_headers, 4)
            assert grown <= baseline, (
                f"An invited member paid {grown} queries for 4 engagements vs "
                f"{baseline} for 1. Role resolution must be batched — see "
                f"_resolve_roles in serializers.py."
            )
        finally:
            for pid in extra:
                client.delete(f"/programs/{pid}", headers=auth_headers)
    finally:
        client.delete(f"/programs/{first}", headers=auth_headers)


def test_viewer_list_query_count_is_constant(client, auth_headers, other_headers):
    first = _make_engagement(client, auth_headers, "Viewer 1")
    _invite(first, role="viewer")
    try:
        baseline = _count_for(client, other_headers, 1)

        extra = []
        for i in range(2, 5):
            pid = _make_engagement(client, auth_headers, f"Viewer {i}")
            _invite(pid, role="viewer")
            extra.append(pid)
        try:
            grown = _count_for(client, other_headers, 4)
            assert grown <= baseline, (
                f"A viewer paid {grown} queries for 4 engagements vs {baseline} for 1."
            )
            listed = client.get("/programs", headers=other_headers).json()["engagements"]
            assert all(e["my_role"] == "viewer" for e in listed)
        finally:
            for pid in extra:
                client.delete(f"/programs/{pid}", headers=auth_headers)
    finally:
        client.delete(f"/programs/{first}", headers=auth_headers)


def test_organization_only_member_list_query_count_is_constant(
    client, auth_headers, other_headers
):
    """Reachable purely through org membership — no direct invitation at all."""
    pids = [_make_engagement(client, auth_headers, f"Org {i}") for i in range(1, 5)]
    try:
        _put_in_org(pids[:1])
        baseline = _count_for(client, other_headers, 1)

        _put_in_org(pids)
        grown = _count_for(client, other_headers, 4)
        assert grown <= baseline, (
            f"An organization member paid {grown} queries for 4 engagements vs "
            f"{baseline} for 1."
        )
    finally:
        for pid in pids:
            client.delete(f"/programs/{pid}", headers=auth_headers)


def test_mixed_access_paths_stay_constant(client, auth_headers, other_headers):
    """Owned, invited and org-reachable engagements in one list."""
    owned_by_other = client.post(
        "/programs", json={"name": "Mixed owned"}, headers=other_headers
    ).json()["id"]
    invited = _make_engagement(client, auth_headers, "Mixed invited")
    _invite(invited)
    org_only = _make_engagement(client, auth_headers, "Mixed org")
    _put_in_org([org_only])
    try:
        baseline = _count_for(client, other_headers, 3)

        more_invited = _make_engagement(client, auth_headers, "Mixed invited 2")
        _invite(more_invited)
        more_org = _make_engagement(client, auth_headers, "Mixed org 2")
        _put_in_org([more_org])
        try:
            grown = _count_for(client, other_headers, 5)
            assert grown <= baseline, (
                f"Mixed access paths cost {grown} queries for 5 engagements vs "
                f"{baseline} for 3."
            )
        finally:
            client.delete(f"/programs/{more_invited}", headers=auth_headers)
            client.delete(f"/programs/{more_org}", headers=auth_headers)
    finally:
        client.delete(f"/programs/{owned_by_other}", headers=other_headers)
        client.delete(f"/programs/{invited}", headers=auth_headers)
        client.delete(f"/programs/{org_only}", headers=auth_headers)


# --------------------------------------------------------------------------- #
# Precedence: owner > organization role > direct engagement membership
# --------------------------------------------------------------------------- #

def test_owner_beats_every_other_grant(client, auth_headers, other_headers):
    """Owning the engagement wins even when an org grants something lower."""
    pid = client.post(
        "/programs", json={"name": "Precedence owner"}, headers=other_headers
    ).json()["id"]
    try:
        _put_in_org([pid], role="viewer")
        listed = client.get("/programs", headers=other_headers).json()["engagements"]
        assert next(e for e in listed if e["id"] == pid)["my_role"] == "owner"
    finally:
        client.delete(f"/programs/{pid}", headers=other_headers)


def test_higher_org_role_beats_lower_engagement_membership(
    client, auth_headers, other_headers
):
    """An org admin invited as a viewer is still an admin — the bug the
    per-engagement resolver was written to fix must survive batching."""
    pid = _make_engagement(client, auth_headers, "Precedence org-admin")
    try:
        _invite(pid, role="viewer")
        _put_in_org([pid], role="admin")
        listed = client.get("/programs", headers=other_headers).json()["engagements"]
        assert next(e for e in listed if e["id"] == pid)["my_role"] == "admin"
    finally:
        client.delete(f"/programs/{pid}", headers=auth_headers)


def test_higher_engagement_membership_beats_lower_org_role(
    client, auth_headers, other_headers
):
    """Precedence is by rank, not by source — the invitation wins here."""
    pid = _make_engagement(client, auth_headers, "Precedence member")
    try:
        _invite(pid, role="member")
        _put_in_org([pid], role="viewer")
        listed = client.get("/programs", headers=other_headers).json()["engagements"]
        assert next(e for e in listed if e["id"] == pid)["my_role"] == "member"
    finally:
        client.delete(f"/programs/{pid}", headers=auth_headers)


def test_batched_roles_match_engagement_access_exactly(
    client, auth_headers, other_headers
):
    """The batch resolver and deps.engagement_access must never disagree."""
    from deps import engagement_access

    owned = client.post(
        "/programs", json={"name": "Parity owned"}, headers=other_headers
    ).json()["id"]
    invited = _make_engagement(client, auth_headers, "Parity invited")
    _invite(invited, role="member")
    org_admin = _make_engagement(client, auth_headers, "Parity org admin")
    _put_in_org([org_admin], role="admin")
    try:
        listed = client.get("/programs", headers=other_headers).json()["engagements"]
        db = SessionLocal()
        try:
            for item in listed:
                row = db.query(Engagement).filter(Engagement.id == item["id"]).first()
                expected = engagement_access(row, OTHER, db) or "viewer"
                assert item["my_role"] == expected, (
                    f"{item['name']}: list says {item['my_role']!r}, "
                    f"engagement_access says {expected!r}"
                )
        finally:
            db.close()
    finally:
        client.delete(f"/programs/{owned}", headers=other_headers)
        client.delete(f"/programs/{invited}", headers=auth_headers)
        client.delete(f"/programs/{org_admin}", headers=auth_headers)
