"""Job -> results provenance: imports stamp job_id, list endpoints filter by it."""
import io


def _job(client, headers, program_id, tool_type="nuclei"):
    """A real queued job. Imports validate job_id against the engagement's own jobs."""
    res = client.post(
        f"/programs/{program_id}/jobs",
        json={"tool_type": tool_type, "target_source": "scope"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


def _import_nuclei(client, headers, program_id, job_id=None, count=2):
    lines = "\n".join(
        f'{{"template-id":"t-{i}","info":{{"name":"Finding {i}","severity":"high"}},"matched-at":"http://ex{i}.com/x"}}'
        for i in range(count)
    )
    data = {"tool_type": "nuclei"}
    if job_id:
        data["job_id"] = job_id
    res = client.post(
        f"/programs/{program_id}/imports",
        files={"file": ("nuclei.jsonl", io.BytesIO(lines.encode()), "application/json")},
        data=data,
        headers=headers,
    )
    assert res.status_code == 200, res.text


def test_scan_items_carry_job_id(client, auth_headers, program_id):
    job = _job(client, auth_headers, program_id)
    _import_nuclei(client, auth_headers, program_id, job_id=job, count=2)
    scans = client.get(f"/programs/{program_id}/scans", headers=auth_headers).json()["scans"]
    assert scans and all(s["job_id"] == job for s in scans)


def test_scans_filter_by_job_id(client, auth_headers, program_id):
    job_a = _job(client, auth_headers, program_id)
    job_b = _job(client, auth_headers, program_id)
    _import_nuclei(client, auth_headers, program_id, job_id=job_a, count=2)
    _import_nuclei(client, auth_headers, program_id, job_id=job_b, count=3)
    only_a = client.get(f"/programs/{program_id}/scans?job_id={job_a}", headers=auth_headers).json()
    assert only_a["total"] == 2
    assert all(s["job_id"] == job_a for s in only_a["scans"])


def test_import_without_job_id_leaves_null(client, auth_headers, program_id):
    _import_nuclei(client, auth_headers, program_id, job_id=None, count=1)
    scans = client.get(f"/programs/{program_id}/scans", headers=auth_headers).json()["scans"]
    assert scans[-1]["job_id"] is None


def test_recon_filter_by_job_id(client, auth_headers, program_id):
    job = _job(client, auth_headers, program_id, tool_type="httpx")
    lines = '{"url":"https://a.example.com","host":"a.example.com","status-code":200}'
    res = client.post(
        f"/programs/{program_id}/imports",
        files={"file": ("httpx.jsonl", io.BytesIO(lines.encode()), "application/json")},
        data={"tool_type": "httpx", "job_id": job},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    res = client.get(f"/programs/{program_id}/recon?job_id={job}", headers=auth_headers).json()
    assert res["total"] == 1
    assert res["recon"][0]["job_id"] == job


def _nuclei_status(client, headers, program_id, job_id):
    return client.post(
        f"/programs/{program_id}/imports",
        files={"file": ("n.jsonl", io.BytesIO(b'{"template-id":"t","info":{"name":"n","severity":"low"},"matched-at":"http://x.test/"}'), "application/json")},
        data={"tool_type": "nuclei", "job_id": job_id},
        headers=headers,
    ).status_code


def test_import_with_an_unknown_job_id_is_rejected_and_stores_nothing(client, auth_headers, program_id):
    """job_id is a real foreign key now; an invented one must not be silently recorded."""
    assert _nuclei_status(client, auth_headers, program_id, "no-such-job") == 404
    assert client.get(f"/programs/{program_id}/scans", headers=auth_headers).json()["total"] == 0


def test_import_cannot_link_another_engagements_job(client, auth_headers, program_id):
    other = client.post("/programs", json={"name": "Second Engagement"}, headers=auth_headers).json()["id"]
    try:
        foreign_job = _job(client, auth_headers, other)
        assert _nuclei_status(client, auth_headers, program_id, foreign_job) == 404
        assert client.get(f"/programs/{program_id}/scans", headers=auth_headers).json()["total"] == 0
    finally:
        client.delete(f"/programs/{other}", headers=auth_headers)
