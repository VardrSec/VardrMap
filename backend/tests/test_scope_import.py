"""Bulk scope import from a HackerOne scope CSV."""

# A compact export modeled on a real program's columns: a bare domain, a full
# URL, a wildcard, an API host, two mobile app ids, and one out-of-scope row.
_CSV = (
    "identifier,asset_type,instruction,eligible_for_bounty,eligible_for_submission,max_severity\n"
    "example.com,URL,,true,true,critical\n"
    "https://www.example.com/blog,OTHER,,false,false,critical\n"
    "*.dev.example.com,WILDCARD,test env,true,true,high\n"
    "api.example.io,API,,true,true,high\n"
    "com.example.app,GOOGLE_PLAY_APP_ID,,true,true,critical\n"
    "123456789,APPLE_STORE_APP_ID,,true,true,critical\n"
)


def _import(client, headers, pid, csv, commit=False, fmt="hackerone"):
    return client.post(
        f"/programs/{pid}/scope/import",
        json={"csv": csv, "commit": commit, "format": fmt},
        headers=headers,
    )


def test_preview_maps_rows_and_writes_nothing(client, auth_headers, program_id):
    res = _import(client, auth_headers, program_id, _CSV, commit=False)
    assert res.status_code == 200
    body = res.json()
    assert body["committed"] is False and body["created"] == 0
    assert body["summary"] == {"in": 5, "out": 1, "duplicates": 0, "skipped": 0, "total_rows": 6}
    by_value = {i["value"]: i for i in body["new_items"]}
    assert by_value["example.com"]["kind"] == "domain"
    assert by_value["https://www.example.com/blog"]["kind"] == "url"
    assert by_value["https://www.example.com/blog"]["scope_type"] == "out"
    assert by_value["*.dev.example.com"]["kind"] == "domain"
    assert by_value["api.example.io"]["kind"] == "api"
    assert by_value["com.example.app"]["kind"] == "mobile"
    assert by_value["123456789"]["kind"] == "mobile"
    assert by_value["api.example.io"]["max_severity"] == "high"
    # A preview writes nothing.
    scope = client.get(f"/programs/{program_id}", headers=auth_headers).json()["scope"]
    assert scope["in"] == [] and scope["out"] == []


def test_commit_inserts_only_new_rows_and_is_reimport_safe(client, auth_headers, program_id):
    first = _import(client, auth_headers, program_id, _CSV, commit=True)
    assert first.status_code == 200 and first.json()["created"] == 6

    scope = client.get(f"/programs/{program_id}", headers=auth_headers).json()["scope"]
    assert len(scope["in"]) == 5 and len(scope["out"]) == 1
    api_item = next(i for i in scope["in"] if i["value"] == "api.example.io")
    assert api_item["max_severity"] == "high" and api_item["kind"] == "api"

    # Re-importing the same export adds nothing — everything is a duplicate.
    again = _import(client, auth_headers, program_id, _CSV, commit=True)
    assert again.json()["created"] == 0
    assert again.json()["summary"]["duplicates"] == 6


def test_invalid_rows_are_skipped_not_fatal(client, auth_headers, program_id):
    csv = (
        "identifier,asset_type,eligible_for_submission,max_severity\n"
        "good.example.com,URL,true,low\n"
        "<script>alert(1)</script>,URL,true,low\n"
        ",URL,true,low\n"
    )
    body = _import(client, auth_headers, program_id, csv, commit=True).json()
    assert body["created"] == 1
    assert body["summary"]["skipped"] == 1  # the empty identifier is ignored, not skipped-with-reason
    assert body["skipped"][0]["reason"] == "invalid characters"


def test_unknown_severity_is_dropped(client, auth_headers, program_id):
    csv = "identifier,asset_type,eligible_for_submission,max_severity\nx.example.com,URL,true,bogus\n"
    item = _import(client, auth_headers, program_id, csv).json()["new_items"][0]
    assert item["max_severity"] == ""


def test_missing_identifier_column_is_rejected(client, auth_headers, program_id):
    res = _import(client, auth_headers, program_id, "host,type\nexample.com,URL\n")
    assert res.status_code == 400


def test_import_requires_write_access(client, auth_headers, other_headers, program_id):
    # A second, unrelated user cannot import into user1's engagement.
    res = _import(client, other_headers, program_id, _CSV, commit=True)
    assert res.status_code == 404
