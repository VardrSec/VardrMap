"""Authorization records: access scoping, window logic, and the active lookup."""

from datetime import datetime, timedelta, timezone


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


NOW = datetime.now(timezone.utc)


def _create(client, headers, program_id, **body):
    return client.post(f"/programs/{program_id}/authorizations", json=body, headers=headers)


def test_create_authorization(client, auth_headers, program_id):
    res = _create(
        client, auth_headers, program_id,
        permits="Testing of the web application and its API.",
        authorized_by="Dana Lee, CTO",
        reference="SOW-2026-014",
        window_start=_iso(NOW - timedelta(days=1)),
        window_end=_iso(NOW + timedelta(days=7)),
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["authorized_by"] == "Dana Lee, CTO"
    assert data["reference"] == "SOW-2026-014"
    assert data["status"] == "active"


def test_create_rejects_a_bad_date(client, auth_headers, program_id):
    res = _create(client, auth_headers, program_id, window_start="last tuesday")
    assert res.status_code == 422
    assert "ISO-8601" in res.text


def test_unauthenticated_is_rejected(client, program_id):
    assert client.get(f"/programs/{program_id}/authorizations").status_code == 401
    assert client.post(f"/programs/{program_id}/authorizations", json={}).status_code == 401


def test_other_user_cannot_read_or_write(client, auth_headers, other_headers, program_id):
    """Scoped through the engagement, so a non-member gets 404 — never 403."""
    _create(client, auth_headers, program_id, permits="x")
    assert client.get(f"/programs/{program_id}/authorizations", headers=other_headers).status_code == 404
    assert _create(client, other_headers, program_id, permits="y").status_code == 404


def test_list_is_newest_first(client, auth_headers, program_id):
    _create(client, auth_headers, program_id, reference="FIRST")
    _create(client, auth_headers, program_id, reference="SECOND")
    items = client.get(f"/programs/{program_id}/authorizations", headers=auth_headers).json()
    assert len(items) >= 2
    assert items[0]["reference"] == "SECOND"


def test_active_returns_none_when_there_is_no_authorization(client, auth_headers, program_id):
    res = client.get(f"/programs/{program_id}/authorization/active", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() is None


def test_active_returns_an_in_window_authorization(client, auth_headers, program_id):
    _create(
        client, auth_headers, program_id,
        reference="CURRENT",
        window_start=_iso(NOW - timedelta(days=1)),
        window_end=_iso(NOW + timedelta(days=1)),
    )
    active = client.get(f"/programs/{program_id}/authorization/active", headers=auth_headers).json()
    assert active is not None
    assert active["reference"] == "CURRENT"


def test_active_ignores_an_expired_window(client, auth_headers, program_id):
    _create(
        client, auth_headers, program_id,
        reference="PAST",
        window_start=_iso(NOW - timedelta(days=30)),
        window_end=_iso(NOW - timedelta(days=1)),
    )
    assert client.get(f"/programs/{program_id}/authorization/active", headers=auth_headers).json() is None


def test_active_ignores_a_future_window(client, auth_headers, program_id):
    _create(
        client, auth_headers, program_id,
        reference="FUTURE",
        window_start=_iso(NOW + timedelta(days=1)),
        window_end=_iso(NOW + timedelta(days=30)),
    )
    assert client.get(f"/programs/{program_id}/authorization/active", headers=auth_headers).json() is None


def test_active_treats_a_missing_window_as_open(client, auth_headers, program_id):
    """Normal for a bounty programme, which has no end date."""
    _create(client, auth_headers, program_id, reference="OPEN_ENDED")
    active = client.get(f"/programs/{program_id}/authorization/active", headers=auth_headers).json()
    assert active is not None
    assert active["reference"] == "OPEN_ENDED"


def test_active_ignores_a_revoked_authorization(client, auth_headers, program_id):
    created = _create(client, auth_headers, program_id, reference="REVOKED").json()
    patched = client.patch(
        f"/programs/{program_id}/authorizations/{created['id']}",
        json={"status": "revoked"},
        headers=auth_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "revoked"
    assert client.get(f"/programs/{program_id}/authorization/active", headers=auth_headers).json() is None


def test_patch_rejects_an_unknown_status(client, auth_headers, program_id):
    created = _create(client, auth_headers, program_id).json()
    res = client.patch(
        f"/programs/{program_id}/authorizations/{created['id']}",
        json={"status": "sort-of-active"},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_patch_on_another_users_program_returns_404(client, auth_headers, other_headers, program_id):
    created = _create(client, auth_headers, program_id).json()
    res = client.patch(
        f"/programs/{program_id}/authorizations/{created['id']}",
        json={"status": "revoked"},
        headers=other_headers,
    )
    assert res.status_code == 404


def test_authorization_from_another_program_is_not_reachable(client, auth_headers, program_id):
    """The id must be scoped to the engagement in the path, not looked up globally."""
    other = client.post("/programs", json={"name": "Other"}, headers=auth_headers).json()["id"]
    created = _create(client, auth_headers, other, reference="ELSEWHERE").json()

    res = client.patch(
        f"/programs/{program_id}/authorizations/{created['id']}",
        json={"status": "revoked"},
        headers=auth_headers,
    )
    assert res.status_code == 404

    client.delete(f"/programs/{other}", headers=auth_headers)


def test_patch_can_clear_window_end(client, auth_headers, program_id):
    """Setting window_end to null via PATCH should clear the date, making the auth open-ended."""
    created = _create(
        client, auth_headers, program_id,
        window_start=_iso(NOW - timedelta(days=1)),
        window_end=_iso(NOW + timedelta(days=7)),
    ).json()
    assert created["window_end"] != ""

    patched = client.patch(
        f"/programs/{program_id}/authorizations/{created['id']}",
        json={"window_end": None},
        headers=auth_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["window_end"] == ""

    active = client.get(f"/programs/{program_id}/authorization/active", headers=auth_headers).json()
    assert active is not None, "Auth should be active now that window_end is cleared"


def test_missing_authorization_returns_404(client, auth_headers, program_id):
    res = client.patch(
        f"/programs/{program_id}/authorizations/nope",
        json={"status": "revoked"},
        headers=auth_headers,
    )
    assert res.status_code == 404
