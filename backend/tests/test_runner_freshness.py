"""Heartbeat freshness is an observation, not a liveness or execution promise."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from routers.runner import _serialize


@pytest.mark.parametrize("seconds,freshness,online", [
    (0, "recent", True), (299, "recent", True),
    (300, "stale", False), (301, "stale", False), (-1, "unknown", False),
])
def test_report_expires_and_future_time_is_unknown(seconds, freshness, online):
    now = datetime(2026, 10, 26, tzinfo=timezone.utc)
    hb = SimpleNamespace(
        last_seen=(now - timedelta(seconds=seconds)).replace(tzinfo=None),
        hostname="fixture", version="1.0", os_info="Linux", tools={},
    )
    row = _serialize(hb, now)
    assert row["freshness"] == freshness
    assert row["online"] is online
    assert row["last_seen"].endswith("+00:00")


def test_status_observation_is_not_cached_and_keeps_owner_boundary(client, auth_headers, other_headers):
    payload = {"hostname": "freshness-owner-only", "version": "0.51.0", "tools": {}}
    assert client.post("/runner/heartbeat", headers=auth_headers, json=payload).status_code == 200
    response = client.get("/runner/status", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["schema_version"] == 1
    assert body["stale_after_seconds"] == 300
    assert datetime.fromisoformat(body["checked_at"]).tzinfo is not None
    row = next(row for row in body["runners"] if row["hostname"] == payload["hostname"])
    assert row["freshness"] == "recent" and row["online"] is True
    other = client.get("/runner/status", headers=other_headers).json()
    assert not any(row["hostname"] == payload["hostname"] for row in other["runners"])
    assert client.get("/runner/status").status_code == 401


def test_aware_non_utc_report_is_serialized_in_utc():
    now = datetime(2026, 10, 26, tzinfo=timezone.utc)
    hb = SimpleNamespace(last_seen=now.astimezone(timezone(timedelta(hours=-5))),
                         hostname="fixture", version="1.0", os_info="Linux", tools={})
    row = _serialize(hb, now)
    assert row["last_seen"] == now.isoformat()
    assert row["freshness"] == "recent"
