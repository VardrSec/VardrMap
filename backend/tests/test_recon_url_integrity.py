"""Recon URLs must survive import intact.

Regression for a data-corruption bug. Every importer ran URLs through ``strip_html``,
which HTML-encodes ``&``: a URL ``?q=1&page=2`` was stored as ``?q=1&amp;page=2``.
Recon URLs are read back as scan targets, so a runner then fetched a URL whose second
parameter was literally named ``amp;page`` -- dalfox tested the wrong parameters.

This covers NEW imports only. Rows already stored are deliberately left untouched (see
docs/recon-url-recovery-plan.md): decoding them would be a guess, because distinct
original URLs collapsed to the same stored value.
"""
import io
import json
from datetime import datetime, timezone

import pytest

from db import get_db
from main import app
from models import ReconItem

URL = "https://t.test/search?q=1&page=2&sort=asc"


def _upload(client, headers, program_id, tool, rows):
    body = "\n".join(json.dumps(r) for r in rows).encode()
    res = client.post(
        f"/programs/{program_id}/imports",
        data={"tool_type": tool},
        files={"file": (f"{tool}.jsonl", io.BytesIO(body), "application/json")},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res


def _recon(client, headers, program_id, source=None):
    rows = client.get(f"/programs/{program_id}/recon?limit=500", headers=headers).json()["recon"]
    return [r for r in rows if source is None or r["source"] == source]


def _legacy_row(program_id, source, url, host="t.test"):
    """A row exactly as the old importer stored it (``&`` encoded), inserted directly."""
    db = next(app.dependency_overrides[get_db]())
    try:
        row = ReconItem(
            program_id=program_id, source=source, url=url, host=host,
            first_seen_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


@pytest.mark.parametrize(
    "tool, row",
    [
        ("gau", {"url": URL}),
        ("katana", {"url": URL, "status_code": 200}),
        ("ffuf", {"url": URL, "input": {"FUZZ": "x"}, "status": 200}),
        ("httpx", {"url": URL, "host": "t.test", "status-code": 200}),
    ],
)
def test_ampersands_survive_every_recon_importer(client, auth_headers, program_id, tool, row):
    _upload(client, auth_headers, program_id, tool, [row])
    (stored,) = _recon(client, auth_headers, program_id, tool)
    assert stored["url"] == URL
    assert "&amp;" not in stored["url"]


def test_nuclei_keeps_the_matched_url_intact(client, auth_headers, program_id):
    _upload(client, auth_headers, program_id, "nuclei", [
        {"template-id": "t", "matched-at": URL, "host": "t.test", "info": {"name": "x", "severity": "low"}},
    ])
    rows = client.get(f"/programs/{program_id}/scans", headers=auth_headers).json()["scans"]
    (row,) = [r for r in rows if r["source"] == "nuclei"]
    assert row["asset"] == URL and row["matched_at"] == URL


def test_the_url_a_runner_will_scan_is_the_url_that_was_discovered(client, auth_headers, program_id):
    """The path that mattered: recon -> job targets -> runner -> dalfox."""
    _upload(client, auth_headers, program_id, "gau", [{"url": URL}])
    preview = client.post(
        f"/programs/{program_id}/jobs/preview",
        json={"tool_type": "dalfox", "target_source": "recon"},
        headers=auth_headers,
    ).json()
    assert URL in preview["sample"]
    assert not any("&amp;" in t for t in preview["sample"])


def test_a_literal_amp_entity_in_an_original_url_is_kept_not_decoded(client, auth_headers, program_id):
    """Archives routinely hold URLs scraped from HTML with a literal ``&amp;`` in them.

    That is a different URL from the ``&`` one, so it must stay different.
    """
    literal = "https://t.test/p?a=1&amp;b=2"
    _upload(client, auth_headers, program_id, "gau", [{"url": literal}])
    (stored,) = _recon(client, auth_headers, program_id, "gau")
    assert stored["url"] == literal


def test_ampersand_and_literal_entity_urls_are_no_longer_collapsed(client, auth_headers, program_id):
    """The collision that makes decoding old rows unsafe, proven absent for new imports.

    The old importer stored both of these as ``a=1&amp;b=2``, so two distinct originals
    shared one row and one dedup key.
    """
    plain, entity = "https://t.test/p?a=1&b=2", "https://t.test/p?a=1&amp;b=2"
    res = _upload(client, auth_headers, program_id, "gau", [{"url": plain}, {"url": entity}])
    assert res.json()["imported_count"] == 2
    assert {r["url"] for r in _recon(client, auth_headers, program_id, "gau")} == {plain, entity}


def test_a_url_is_never_stored_as_markup(client, auth_headers, program_id):
    """`<`/`>` are percent-encoded rather than deleted: still the same target, never a tag."""
    _upload(client, auth_headers, program_id, "gau", [{"url": "https://t.test/<script>x</script>?a=1&b=2"}])
    (stored,) = _recon(client, auth_headers, program_id, "gau")
    assert stored["url"] == "https://t.test/%3Cscript%3Ex%3C/script%3E?a=1&b=2"
    assert "<" not in stored["url"] and ">" not in stored["url"]


def test_titles_are_still_sanitised(client, auth_headers, program_id):
    """Only URL-valued fields became lossless; descriptive text keeps the sanitiser."""
    _upload(client, auth_headers, program_id, "httpx", [
        {"url": "https://t.test/", "host": "t.test", "title": "<img src=x onerror=alert(1)>Home", "status-code": 200},
    ])
    (stored,) = _recon(client, auth_headers, program_id, "httpx")
    assert "<" not in stored["title"] and "onerror" not in stored["title"]


def test_control_characters_are_removed_and_length_is_bounded(client, auth_headers, program_id):
    _upload(client, auth_headers, program_id, "gau", [{"url": "https://t.test/a\x00b\x07?q=1&r=2"}])
    (stored,) = _recon(client, auth_headers, program_id, "gau")
    assert stored["url"] == "https://t.test/ab?q=1&r=2"
    _upload(client, auth_headers, program_id, "gau", [{"url": "https://t.test/" + "x" * 20000}])
    assert max(len(r["url"]) for r in _recon(client, auth_headers, program_id, "gau")) <= 8192


# ── the boundary with rows stored before this fix ───────────────────────────


def test_existing_rows_are_left_exactly_as_stored(client, auth_headers, program_id):
    """No import may rewrite history: decoding is a guess, so it is a separate, reviewed step."""
    legacy_id = _legacy_row(program_id, "gau", "https://t.test/search?q=1&amp;page=2&amp;sort=asc")
    _upload(client, auth_headers, program_id, "gau", [{"url": "https://t.test/other?z=9&y=8"}])
    old = next(r for r in _recon(client, auth_headers, program_id, "gau") if r["id"] == legacy_id)
    assert old["url"] == "https://t.test/search?q=1&amp;page=2&amp;sort=asc"


def test_reimporting_a_legacy_url_adds_the_correct_row_beside_the_old_one(client, auth_headers, program_id):
    """Documented boundary behaviour, pinned so it is a conscious choice.

    Dedup is on the exact URL string, so the correct URL does not match the legacy
    encoded row and is stored as its own row; the legacy row is untouched. The two are
    reconciled by the recovery step, which has the evidence (the correct row) to do it
    safely. Skipping the import instead would silently drop the correct URL.
    """
    legacy = "https://t.test/search?q=1&amp;page=2&amp;sort=asc"
    legacy_id = _legacy_row(program_id, "gau", legacy)
    res = _upload(client, auth_headers, program_id, "gau", [{"url": URL}])
    assert res.json()["imported_count"] == 1
    urls = {r["id"]: r["url"] for r in _recon(client, auth_headers, program_id, "gau")}
    assert set(urls.values()) == {legacy, URL}
    assert urls[legacy_id] == legacy


def test_a_reprobed_httpx_host_heals_its_own_url(client, auth_headers, program_id):
    """httpx matches by host and enriches in place, so its legacy rows repair themselves."""
    legacy_id = _legacy_row(program_id, "httpx", "https://t.test/search?q=1&amp;page=2")
    res = _upload(client, auth_headers, program_id, "httpx", [
        {"url": "https://t.test/search?q=1&page=2", "host": "t.test", "status-code": 200},
    ])
    assert res.json()["new_count"] == 0  # enriched, not duplicated
    (row,) = _recon(client, auth_headers, program_id, "httpx")
    assert row["id"] == legacy_id and row["url"] == "https://t.test/search?q=1&page=2"
