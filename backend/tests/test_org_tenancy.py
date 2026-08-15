"""Tenant isolation across organizations.

The gap this closes: job, schedule, and client endpoints filtered on
`owner_github_id == current_user`, so a teammate who could read an engagement's
findings could not see its jobs, and a firm could not share a runner fleet.

These tests assert both directions — that a teammate gains access, and that a
stranger gains nothing. The second matters more: widening an access check is
exactly the change that accidentally widens it too far.
"""
import pytest

from db import SessionLocal
from deps import ROLE_RANK, engagement_access, personal_org
from models import Engagement, EngagementMember, Organization, OrganizationMember

USER1 = "gh_user1"   # auth_headers
USER2 = "gh_user2"   # other_headers


def _db():
    return SessionLocal()


@pytest.fixture
def engagement(client, auth_headers):
    res = client.post("/programs", json={"name": "Org Tenancy"}, headers=auth_headers)
    pid = res.json()["id"]
    yield pid
    client.delete(f"/programs/{pid}", headers=auth_headers)


def _put_in_org(pid: str, github_ids: dict[str, str]) -> str:
    """Attach the engagement to a fresh org with the given members and roles."""
    db = _db()
    try:
        org = Organization(name="Acme Security", personal_for_github_id="")
        db.add(org)
        db.flush()
        for gh, role in github_ids.items():
            db.add(OrganizationMember(org_id=org.id, github_id=gh, role=role))
        db.query(Engagement).filter(Engagement.id == pid).update({"org_id": org.id})
        db.commit()
        return org.id
    finally:
        db.close()


def _create_job(client, headers, pid):
    return client.post(
        f"/programs/{pid}/jobs",
        json={"tool_type": "httpx", "target_source": "scope"},
        headers=headers,
    )


# --------------------------------------------------------------------------- #
# Access resolution
# --------------------------------------------------------------------------- #

def test_owner_always_has_owner_role(engagement):
    db = _db()
    try:
        row = db.query(Engagement).filter(Engagement.id == engagement).first()
        assert engagement_access(row, USER1, db) == "owner"
    finally:
        db.close()


def test_stranger_has_no_access(engagement):
    db = _db()
    try:
        row = db.query(Engagement).filter(Engagement.id == engagement).first()
        assert engagement_access(row, "nobody", db) is None
    finally:
        db.close()


def test_org_membership_grants_access(engagement):
    _put_in_org(engagement, {USER2: "member"})
    db = _db()
    try:
        row = db.query(Engagement).filter(Engagement.id == engagement).first()
        assert engagement_access(row, USER2, db) == "member"
    finally:
        db.close()


def test_highest_grant_wins_when_several_apply(engagement):
    """Org 'viewer' plus engagement 'member' must resolve to member, not viewer."""
    _put_in_org(engagement, {USER2: "viewer"})
    db = _db()
    try:
        db.add(
            EngagementMember(
                program_id=engagement, owner_github_id=USER1,
                member_github_id=USER2, role="member",
            )
        )
        db.commit()
        row = db.query(Engagement).filter(Engagement.id == engagement).first()
        assert engagement_access(row, USER2, db) == "member"
    finally:
        db.close()


def test_role_rank_is_totally_ordered():
    assert ROLE_RANK["owner"] > ROLE_RANK["admin"] > ROLE_RANK["member"] > ROLE_RANK["viewer"]


# --------------------------------------------------------------------------- #
# Isolation through the API — the part that must not widen too far
# --------------------------------------------------------------------------- #

def test_stranger_cannot_read_the_engagement(client, other_headers, engagement):
    assert client.get(f"/programs/{engagement}", headers=other_headers).status_code == 404


def test_stranger_cannot_create_a_job(client, other_headers, engagement):
    assert _create_job(client, other_headers, engagement).status_code == 404


def test_stranger_cannot_see_the_engagement_jobs(client, auth_headers, other_headers, engagement):
    _create_job(client, auth_headers, engagement)
    res = client.get(f"/programs/{engagement}/jobs", headers=other_headers)
    assert res.status_code == 404


def test_org_member_can_read_the_engagement(client, other_headers, engagement):
    _put_in_org(engagement, {USER2: "member"})
    assert client.get(f"/programs/{engagement}", headers=other_headers).status_code == 200


def test_org_member_can_operate_jobs(client, auth_headers, other_headers, engagement):
    """The actual regression: a teammate could read findings but not jobs."""
    _put_in_org(engagement, {USER2: "member"})
    created = _create_job(client, auth_headers, engagement)
    assert created.status_code == 200

    listed = client.get(f"/programs/{engagement}/jobs", headers=other_headers)
    assert listed.status_code == 200
    assert any(j["id"] == created.json()["id"] for j in listed.json()["jobs"])


def test_org_member_sees_the_job_in_the_pending_queue(
    client, auth_headers, other_headers, engagement
):
    """A shared runner fleet is the point — the queue must not be per-user."""
    _put_in_org(engagement, {USER2: "member"})
    job_id = _create_job(client, auth_headers, engagement).json()["id"]

    pending = client.get("/jobs/pending", headers=other_headers)
    assert pending.status_code == 200
    assert any(j["id"] == job_id for j in pending.json()["jobs"])


def test_stranger_never_sees_the_job_in_the_pending_queue(
    client, auth_headers, other_headers, engagement
):
    job_id = _create_job(client, auth_headers, engagement).json()["id"]
    pending = client.get("/jobs/pending", headers=other_headers)
    assert not any(j["id"] == job_id for j in pending.json()["jobs"])


def test_org_viewer_cannot_write(client, other_headers, engagement):
    _put_in_org(engagement, {USER2: "viewer"})
    res = _create_job(client, other_headers, engagement)
    assert res.status_code == 403


def test_org_member_cannot_claim_a_stranger_engagement_job(
    client, auth_headers, other_headers, engagement
):
    """Membership in *some* org must not grant access to another org's job."""
    _put_in_org(engagement, {USER1: "owner"})  # user2 deliberately excluded
    job_id = _create_job(client, auth_headers, engagement).json()["id"]
    assert client.post(f"/jobs/{job_id}/claim", headers=other_headers).status_code == 404


# --------------------------------------------------------------------------- #
# Personal organizations
# --------------------------------------------------------------------------- #

def test_personal_org_is_created_once_and_reused():
    db = _db()
    try:
        first = personal_org("solo-user", db)
        db.commit()
        second = personal_org("solo-user", db)
        db.commit()
        assert first.id == second.id
    finally:
        db.close()


def test_personal_org_makes_its_user_an_owner():
    db = _db()
    try:
        org = personal_org("solo-owner", db)
        db.commit()
        role = (
            db.query(OrganizationMember.role)
            .filter(
                OrganizationMember.org_id == org.id,
                OrganizationMember.github_id == "solo-owner",
            )
            .first()
        )
        assert role[0] == "owner"
    finally:
        db.close()
