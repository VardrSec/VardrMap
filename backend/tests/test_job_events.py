"""Tests for the job_events endpoints.

Coverage:
- POST /jobs/{id}/events — VardrRunner posts a lifecycle event
- GET  /jobs/{id}/events — frontend polls events for a job

BOLA checks: wrong-user gets 404 (not 403) on both endpoints.
"""

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job(client, program_id, headers):
    res = client.post(
        f"/programs/{program_id}/jobs",
        json={"tool_type": "httpx", "target_source": "scope"},
        headers=headers,
    )
    assert res.status_code == 200
    return res.json()["id"]


def _post_event(client, job_id, headers, kind="started", text=""):
    return client.post(
        f"/jobs/{job_id}/events",
        json={"kind": kind, "text": text},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# POST /jobs/{id}/events
# ---------------------------------------------------------------------------

class TestPostJobEvent:
    def test_create_event_success(self, client, program_id, auth_headers):
        jid = _make_job(client, program_id, auth_headers)
        res = _post_event(client, jid, auth_headers, kind="started", text="runner claimed job")
        assert res.status_code == 201
        data = res.json()
        assert data["job_id"] == jid
        assert data["kind"] == "started"
        assert data["text"] == "runner claimed job"
        assert data["id"]
        assert data["created_at"]

    def test_create_multiple_event_kinds(self, client, program_id, auth_headers):
        jid = _make_job(client, program_id, auth_headers)
        for kind in ("started", "targets_resolved", "running", "uploaded", "done"):
            res = _post_event(client, jid, auth_headers, kind=kind, text=f"event: {kind}")
            assert res.status_code == 201
            assert res.json()["kind"] == kind

    def test_create_event_default_text(self, client, program_id, auth_headers):
        jid = _make_job(client, program_id, auth_headers)
        res = client.post(
            f"/jobs/{jid}/events",
            json={"kind": "done"},
            headers=auth_headers,
        )
        assert res.status_code == 201
        assert res.json()["text"] == ""

    def test_unauthorized(self, client, program_id, auth_headers):
        jid = _make_job(client, program_id, auth_headers)
        res = _post_event(client, jid, {})
        assert res.status_code == 401

    def test_wrong_user_404(self, client, program_id, auth_headers, other_headers):
        jid = _make_job(client, program_id, auth_headers)
        res = _post_event(client, jid, other_headers)
        assert res.status_code == 404

    def test_nonexistent_job_404(self, client, auth_headers):
        res = _post_event(client, "no-such-job", auth_headers)
        assert res.status_code == 404

    def test_invalid_kind_422(self, client, program_id, auth_headers):
        jid = _make_job(client, program_id, auth_headers)
        res = client.post(
            f"/jobs/{jid}/events",
            json={"kind": "not_a_real_kind", "text": "x"},
            headers=auth_headers,
        )
        assert res.status_code == 422

    def test_text_too_long_422(self, client, program_id, auth_headers):
        jid = _make_job(client, program_id, auth_headers)
        res = client.post(
            f"/jobs/{jid}/events",
            json={"kind": "log", "text": "x" * 2001},
            headers=auth_headers,
        )
        assert res.status_code == 422


# ---------------------------------------------------------------------------
# GET /jobs/{id}/events
# ---------------------------------------------------------------------------

class TestGetJobEvents:
    def test_get_events_empty(self, client, program_id, auth_headers):
        jid = _make_job(client, program_id, auth_headers)
        res = client.get(f"/jobs/{jid}/events", headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["events"] == []

    def test_get_events_returns_in_order(self, client, program_id, auth_headers):
        jid = _make_job(client, program_id, auth_headers)
        for kind in ("started", "running", "done"):
            _post_event(client, jid, auth_headers, kind=kind)
        res = client.get(f"/jobs/{jid}/events", headers=auth_headers)
        assert res.status_code == 200
        kinds = [e["kind"] for e in res.json()["events"]]
        assert kinds == ["started", "running", "done"]

    def test_get_events_fields(self, client, program_id, auth_headers):
        jid = _make_job(client, program_id, auth_headers)
        _post_event(client, jid, auth_headers, kind="targets_resolved", text="4 targets from scope")
        res = client.get(f"/jobs/{jid}/events", headers=auth_headers)
        event = res.json()["events"][0]
        assert event["kind"] == "targets_resolved"
        assert event["text"] == "4 targets from scope"
        assert event["job_id"] == jid
        assert "created_at" in event

    def test_get_events_unauthorized(self, client, program_id, auth_headers):
        jid = _make_job(client, program_id, auth_headers)
        res = client.get(f"/jobs/{jid}/events")
        assert res.status_code == 401

    def test_get_events_wrong_user_404(self, client, program_id, auth_headers, other_headers):
        jid = _make_job(client, program_id, auth_headers)
        _post_event(client, jid, auth_headers, kind="started")
        res = client.get(f"/jobs/{jid}/events", headers=other_headers)
        assert res.status_code == 404

    def test_get_events_nonexistent_job_404(self, client, auth_headers):
        res = client.get("/jobs/does-not-exist/events", headers=auth_headers)
        assert res.status_code == 404

    def test_events_cascade_delete_with_job(self, client, program_id, auth_headers):
        """Deleting the program (which cascades to jobs) also deletes job events."""
        jid = _make_job(client, program_id, auth_headers)
        _post_event(client, jid, auth_headers, kind="started")
        # Delete the program → jobs → events cascade
        client.delete(f"/programs/{program_id}", headers=auth_headers)
        # Job and its events are gone; confirm by trying a new program-less fetch
        res = client.get(f"/jobs/{jid}/events", headers=auth_headers)
        assert res.status_code == 404
