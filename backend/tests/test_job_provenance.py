"""Job -> results provenance: imports stamp job_id, list endpoints filter by it."""
import io


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
    _import_nuclei(client, auth_headers, program_id, job_id="job-123", count=2)
    scans = client.get(f"/programs/{program_id}/scans", headers=auth_headers).json()["scans"]
    assert scans and all(s["job_id"] == "job-123" for s in scans)


def test_scans_filter_by_job_id(client, auth_headers, program_id):
    _import_nuclei(client, auth_headers, program_id, job_id="job-A", count=2)
    _import_nuclei(client, auth_headers, program_id, job_id="job-B", count=3)
    only_a = client.get(f"/programs/{program_id}/scans?job_id=job-A", headers=auth_headers).json()
    assert only_a["total"] == 2
    assert all(s["job_id"] == "job-A" for s in only_a["scans"])


def test_import_without_job_id_leaves_null(client, auth_headers, program_id):
    _import_nuclei(client, auth_headers, program_id, job_id=None, count=1)
    scans = client.get(f"/programs/{program_id}/scans", headers=auth_headers).json()["scans"]
    assert scans[-1]["job_id"] is None


def test_recon_filter_by_job_id(client, auth_headers, program_id):
    lines = '{"url":"https://a.example.com","host":"a.example.com","status-code":200}'
    client.post(
        f"/programs/{program_id}/imports",
        files={"file": ("httpx.jsonl", io.BytesIO(lines.encode()), "application/json")},
        data={"tool_type": "httpx", "job_id": "job-R"},
        headers=auth_headers,
    )
    res = client.get(f"/programs/{program_id}/recon?job_id=job-R", headers=auth_headers).json()
    assert res["total"] == 1
    assert res["recon"][0]["job_id"] == "job-R"
