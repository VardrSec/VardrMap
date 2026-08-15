"""Asset graph — canonical identity, upserts, edges, and the read API.

The identity function is the load-bearing part. Merging two assets that are
actually different is unrecoverable (after the merge there is no record of what
was distinct), so these tests pin both directions: equivalent spellings must
converge, and lookalikes must never.
"""
import pytest

import assets as ag
from db import SessionLocal
from models import Asset, AssetRelationship, ReconItem, Service


# --------------------------------------------------------------------------- #
# Canonical identity — pure, no database
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "observed",
    [
        "api.acme.com",
        "API.ACME.COM",
        "api.acme.com.",
        "http://api.acme.com/v1/users",   # http → port 80 … see next test
    ],
)
def test_host_spellings_parse_to_the_same_hostname(observed):
    assert ag.parse(observed).hostname == "api.acme.com"


def test_scheme_implies_the_default_port():
    """https and http carry a port even when it is not written."""
    assert ag.parse("https://api.acme.com").port == 443
    assert ag.parse("http://api.acme.com").port == 80
    assert ag.parse("api.acme.com").port is None


def test_explicit_port_wins_over_the_scheme_default():
    assert ag.parse("https://api.acme.com:8443/x").port == 8443


def test_bare_host_and_https_url_are_different_assets():
    """A host and a service on that host are genuinely different nodes."""
    assert ag.parse("api.acme.com").canonical_key != ag.parse("https://api.acme.com").canonical_key


def test_credentials_are_never_part_of_an_identity():
    assert ag.parse("https://user:pass@api.acme.com/x").hostname == "api.acme.com"


def test_ipv4_is_classified_as_an_ip_asset():
    identity = ag.parse("93.184.216.34")
    assert identity.asset_type == ag.IP and identity.ip == "93.184.216.34"


def test_ipv6_literal_with_port_is_parsed():
    identity = ag.parse("[2001:db8::1]:8080")
    assert identity.asset_type == ag.IP and identity.port == 8080


def test_lookalike_hosts_never_collide():
    assert ag.parse("acme.com").canonical_key != ag.parse("notacme.com").canonical_key


@pytest.mark.parametrize("observed", ["", "   ", "not a host", "localhost", "://"])
def test_unclassifiable_input_returns_none(observed):
    """None is a real answer — a phantom node would poison every correlation."""
    assert ag.parse(observed) is None


# --------------------------------------------------------------------------- #
# Upsert and edges
# --------------------------------------------------------------------------- #

@pytest.fixture
def engagement(client, auth_headers):
    pid = client.post("/programs", json={"name": "Assets"}, headers=auth_headers).json()["id"]
    yield pid
    client.delete(f"/programs/{pid}", headers=auth_headers)


def test_upsert_creates_once_and_reuses(engagement):
    db = SessionLocal()
    try:
        a = ag.upsert(db, engagement, "api.acme.com", source="httpx")
        db.commit()
        b = ag.upsert(db, engagement, "API.acme.com.", source="nuclei")
        db.commit()
        assert a.id == b.id
        assert db.query(Asset).filter(Asset.program_id == engagement).count() == 1
    finally:
        db.close()


def test_upsert_refreshes_last_seen(engagement):
    db = SessionLocal()
    try:
        first = ag.upsert(db, engagement, "api.acme.com")
        db.commit()
        original = first.last_seen_at
        again = ag.upsert(db, engagement, "api.acme.com")
        db.commit()
        assert again.last_seen_at >= original
    finally:
        db.close()


def test_upsert_returns_none_for_unclassifiable(engagement):
    db = SessionLocal()
    try:
        assert ag.upsert(db, engagement, "not a host") is None
    finally:
        db.close()


def test_assets_are_scoped_per_engagement(client, auth_headers, engagement):
    """The same hostname in two engagements is two nodes — they are different
    attack surfaces that happen to share a name."""
    other = client.post("/programs", json={"name": "Other"}, headers=auth_headers).json()["id"]
    db = SessionLocal()
    try:
        a = ag.upsert(db, engagement, "api.acme.com")
        b = ag.upsert(db, other, "api.acme.com")
        db.commit()
        assert a.id != b.id
    finally:
        db.close()
        client.delete(f"/programs/{other}", headers=auth_headers)


def test_relate_creates_edge_once(engagement):
    db = SessionLocal()
    try:
        host = ag.upsert(db, engagement, "api.acme.com")
        svc = ag.upsert(db, engagement, "api.acme.com", default_port=443)
        ag.relate(db, engagement, host, svc, ag.EXPOSES)
        ag.relate(db, engagement, host, svc, ag.EXPOSES)
        db.commit()
        assert db.query(AssetRelationship).filter(
            AssetRelationship.program_id == engagement
        ).count() == 1
    finally:
        db.close()


def test_self_edges_are_refused(engagement):
    """An asset related to itself carries no information and makes cycles trivial."""
    db = SessionLocal()
    try:
        host = ag.upsert(db, engagement, "api.acme.com")
        db.commit()
        assert ag.relate(db, engagement, host, host, ag.EXPOSES) is None
    finally:
        db.close()


def test_parent_domain_links_only_to_a_known_parent(engagement):
    """No public-suffix list, so we never invent a parent that does not exist."""
    db = SessionLocal()
    try:
        child = ag.upsert(db, engagement, "api.acme.com")
        db.commit()
        assert ag.parent_domain(db, engagement, child) is None

        parent = ag.upsert(db, engagement, "acme.com")
        db.commit()
        assert ag.parent_domain(db, engagement, child).id == parent.id
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Ingestion wiring — the graph must populate from real imports
# --------------------------------------------------------------------------- #

def test_service_upload_creates_host_and_service_nodes_and_an_edge(
    client, auth_headers, engagement
):
    res = client.post(
        f"/programs/{engagement}/services",
        json={"services": [{"host": "db.acme.com", "port": 5432, "service_name": "postgres"}]},
        headers=auth_headers,
    )
    assert res.status_code in (200, 201), res.text

    db = SessionLocal()
    try:
        nodes = db.query(Asset).filter(Asset.program_id == engagement).all()
        keys = {n.canonical_key for n in nodes}
        assert "domain:db.acme.com" in keys           # the host
        assert "domain:db.acme.com:5432" in keys      # the exposed service

        edge = db.query(AssetRelationship).filter(
            AssetRelationship.program_id == engagement,
            AssetRelationship.relationship == ag.EXPOSES,
        ).first()
        assert edge is not None

        svc = db.query(Service).filter(Service.program_id == engagement).first()
        assert svc.asset_id is not None
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Read API
# --------------------------------------------------------------------------- #

def test_list_assets_returns_created_nodes(client, auth_headers, engagement):
    db = SessionLocal()
    try:
        ag.upsert(db, engagement, "api.acme.com", source="httpx")
        db.commit()
    finally:
        db.close()

    res = client.get(f"/programs/{engagement}/assets", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["assets"][0]["hostname"] == "api.acme.com"


def test_list_assets_filters_by_hostname_prefix(client, auth_headers, engagement):
    db = SessionLocal()
    try:
        ag.upsert(db, engagement, "api.acme.com")
        ag.upsert(db, engagement, "www.acme.com")
        db.commit()
    finally:
        db.close()

    res = client.get(f"/programs/{engagement}/assets?q=api", headers=auth_headers)
    assert [a["hostname"] for a in res.json()["assets"]] == ["api.acme.com"]


def test_asset_detail_returns_edges_and_counts(client, auth_headers, engagement):
    db = SessionLocal()
    try:
        host = ag.upsert(db, engagement, "api.acme.com")
        svc = ag.upsert(db, engagement, "api.acme.com", default_port=443)
        ag.relate(db, engagement, host, svc, ag.EXPOSES)
        db.add(ReconItem(program_id=engagement, source="httpx",
                         host="api.acme.com", asset_id=host.id))
        db.commit()
        host_id = host.id
    finally:
        db.close()

    res = client.get(f"/programs/{engagement}/assets/{host_id}", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["counts"]["recon"] == 1
    assert body["relationships"][0]["relationship"] == ag.EXPOSES
    assert body["relationships"][0]["direction"] == "out"


def test_asset_detail_404s_for_another_engagements_asset(client, auth_headers, engagement):
    other = client.post("/programs", json={"name": "Other2"}, headers=auth_headers).json()["id"]
    db = SessionLocal()
    try:
        foreign = ag.upsert(db, other, "secret.acme.com")
        db.commit()
        foreign_id = foreign.id
    finally:
        db.close()

    res = client.get(f"/programs/{engagement}/assets/{foreign_id}", headers=auth_headers)
    assert res.status_code == 404
    client.delete(f"/programs/{other}", headers=auth_headers)


def test_stranger_cannot_list_assets(client, other_headers, engagement):
    assert client.get(f"/programs/{engagement}/assets", headers=other_headers).status_code == 404


def test_url_and_bare_host_observations_converge_on_one_node(engagement):
    """Regression: the whole point of the graph.

    A recon row recorded as `https://api.acme.com/v1` and a finding recorded as
    `api.acme.com` are observations of the same host. An early version linked
    them to `domain:api.acme.com:443` and `domain:api.acme.com` respectively —
    two nodes that never join, leaving the graph as fragmented as the free-text
    columns it replaced.
    """
    db = SessionLocal()
    try:
        from_url = ag.upsert(db, engagement, "https://api.acme.com/v1", host_level=True)
        from_host = ag.upsert(db, engagement, "api.acme.com", host_level=True)
        from_upper = ag.upsert(db, engagement, "API.ACME.COM.", host_level=True)
        db.commit()
        assert from_url.id == from_host.id == from_upper.id
        assert db.query(Asset).filter(Asset.program_id == engagement).count() == 1
    finally:
        db.close()


def test_service_nodes_stay_port_specific(engagement):
    """Host-level correlation must not collapse distinct services onto one node."""
    db = SessionLocal()
    try:
        http = ag.upsert(db, engagement, "api.acme.com", default_port=443)
        postgres = ag.upsert(db, engagement, "api.acme.com", default_port=5432)
        db.commit()
        assert http.id != postgres.id
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Regressions — ingestion paths that were never wired to the graph
# --------------------------------------------------------------------------- #

def test_httpx_import_links_rows_to_assets(client, auth_headers, engagement):
    """Reported gap: httpx went through the enrich/upsert path, which never
    called the linker — so the primary recon source stayed off the graph."""
    import json
    import io

    payload = [{"url": "https://api.acme.com", "host": "api.acme.com", "status_code": 200}]
    res = client.post(
        f"/programs/{engagement}/imports",
        files={"file": ("httpx.json", io.BytesIO(json.dumps(payload).encode()), "application/json")},
        data={"tool_type": "httpx"},
        headers=auth_headers,
    )
    assert res.status_code in (200, 201), res.text

    db = SessionLocal()
    try:
        rows = db.query(ReconItem).filter(ReconItem.program_id == engagement).all()
        assert rows, "import produced no rows"
        assert all(r.asset_id for r in rows), "httpx rows must be linked to an asset"
    finally:
        db.close()


def test_new_finding_is_linked_to_its_asset(client, auth_headers, engagement):
    """Reported gap: findings created through the API stayed unlinked, so they
    dropped out of every per-asset view."""
    from models import Finding

    created = client.post(
        f"/programs/{engagement}/findings",
        json={"title": "SQLi", "severity": "high", "asset": "https://api.acme.com/v1"},
        headers=auth_headers,
    )
    assert created.status_code in (200, 201), created.text

    db = SessionLocal()
    try:
        finding = db.query(Finding).filter(Finding.id == created.json()["id"]).first()
        assert finding.asset_id is not None
        node = db.query(Asset).filter(Asset.id == finding.asset_id).first()
        assert node.canonical_key == "domain:api.acme.com"
    finally:
        db.close()


def test_finding_relinks_when_its_asset_changes(client, auth_headers, engagement):
    from models import Finding

    created = client.post(
        f"/programs/{engagement}/findings",
        json={"title": "XSS", "severity": "low", "asset": "api.acme.com"},
        headers=auth_headers,
    ).json()

    client.patch(
        f"/programs/{engagement}/findings/{created['id']}",
        json={"asset": "www.acme.com"},
        headers=auth_headers,
    )

    db = SessionLocal()
    try:
        finding = db.query(Finding).filter(Finding.id == created["id"]).first()
        node = db.query(Asset).filter(Asset.id == finding.asset_id).first()
        assert node.hostname == "www.acme.com"
    finally:
        db.close()


def test_finding_and_recon_on_the_same_host_share_one_asset(client, auth_headers, engagement):
    """The correlation the graph exists for, end to end through the API."""
    import io
    import json
    from models import Finding

    client.post(
        f"/programs/{engagement}/imports",
        files={"file": ("h.json", io.BytesIO(json.dumps(
            [{"url": "https://api.acme.com", "host": "api.acme.com"}]).encode()), "application/json")},
        data={"tool_type": "httpx"},
        headers=auth_headers,
    )
    finding = client.post(
        f"/programs/{engagement}/findings",
        json={"title": "IDOR", "severity": "high", "asset": "api.acme.com"},
        headers=auth_headers,
    ).json()

    db = SessionLocal()
    try:
        recon = db.query(ReconItem).filter(ReconItem.program_id == engagement).first()
        found = db.query(Finding).filter(Finding.id == finding["id"]).first()
        assert recon.asset_id and found.asset_id
        assert recon.asset_id == found.asset_id
    finally:
        db.close()
