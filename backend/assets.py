"""Canonical asset identity and graph upserts.

The problem this solves: a host existed as five unrelated free-text columns —
`recon_items.host`, `recon_items.url`, `services.host`, `scan_items.asset`,
`findings.asset` — with no foreign key between them. Identity resolution was
string comparison ("url when present, else host"), so `api.acme.com`,
`https://api.acme.com/` and `api.acme.com:443` were three different things.

Nothing could be correlated: a finding could not be traced to the service that
exposed it, risk could not be aggregated per host, and attack surface could not
be diffed over time.

Identity is a pure function of the observed string. `canonical_key` is the join
key, and it is deliberately conservative — merging two assets that are actually
different is unrecoverable without knowing what was merged, so anything that
cannot be classified stays unclassified rather than being forced into a bucket.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from models import Asset, AssetRelationship

# Asset types. Additive — a new type must never change an existing canonical key,
# because the key is a stored join column.
DOMAIN = "domain"
IP = "ip_address"
HOST = "host"
SERVICE = "service"
WEB_APP = "web_application"
API_ENDPOINT = "api_endpoint"

# Relationship verbs on the edge table.
RESOLVES_TO = "resolves_to"
HOSTED_ON = "hosted_on"
EXPOSES = "exposes"
DISCOVERED_FROM = "discovered_from"
BELONGS_TO = "belongs_to"
VULNERABLE_TO = "vulnerable_to"


@dataclass(frozen=True)
class AssetIdentity:
    asset_type: str
    hostname: str = ""
    ip: str = ""
    port: Optional[int] = None
    scheme: str = ""

    @property
    def canonical_key(self) -> str:
        """Stable join key. Two observations of the same thing produce the same
        string; two different things never do."""
        base = self.ip or self.hostname
        if self.port:
            return f"{self.asset_type}:{base}:{self.port}"
        return f"{self.asset_type}:{base}"

    @property
    def label(self) -> str:
        base = self.ip or self.hostname
        return f"{base}:{self.port}" if self.port else base


def parse(observed: str, default_port: Optional[int] = None) -> Optional[AssetIdentity]:
    """Reduce an observed string to a canonical identity, or None if unclassifiable.

    None is a real answer. Forcing an unparseable value into an asset would
    create a phantom node that pollutes every downstream correlation, and there
    is no way to unmerge it later.
    """
    raw = (observed or "").strip()
    if not raw:
        return None

    scheme = ""
    remainder = raw
    if "://" in remainder:
        scheme, remainder = remainder.split("://", 1)
        scheme = scheme.lower()

    authority = remainder.split("/", 1)[0]
    # Strip credentials — they must never become part of an identity.
    if "@" in authority:
        authority = authority.split("@", 1)[1]

    port = default_port
    host = authority
    if host.startswith("["):  # bracketed IPv6, optionally with a port
        close = host.find("]")
        if close == -1:
            return None
        inner, rest = host[1:close], host[close + 1:]
        host = inner
        if rest.startswith(":") and rest[1:].isdigit():
            port = int(rest[1:])
    elif host.count(":") == 1:
        head, tail = host.split(":", 1)
        if tail.isdigit():
            host, port = head, int(tail)

    host = host.rstrip(".").lower()
    if not host:
        return None

    if port is None and scheme in ("http", "https"):
        port = 443 if scheme == "https" else 80

    try:
        ipaddress.ip_address(host)
        return AssetIdentity(asset_type=IP, ip=host, port=port, scheme=scheme)
    except ValueError:
        pass

    if " " in host or "." not in host:
        return None
    return AssetIdentity(asset_type=DOMAIN, hostname=host, port=port, scheme=scheme)


def upsert(
    db: Session,
    program_id: str,
    observed: str,
    *,
    source: str = "",
    confidence: str = "confirmed",
    default_port: Optional[int] = None,
    host_level: bool = False,
    seen_at: Optional[datetime] = None,
) -> Optional[Asset]:
    """Find or create the asset for an observed string, refreshing last_seen_at.

    `host_level=True` drops the port, so an observation written as
    `https://api.acme.com/v1` resolves to the same node as one written
    `api.acme.com`. Correlation happens at the host: a finding recorded against
    a bare hostname and a recon row recorded as a URL are observations of the
    same thing, and if they land on different nodes the graph has achieved
    nothing. Port-specific nodes exist for services, which link back to their
    host with an `exposes` edge.

    Returns None when the observation cannot be classified — callers treat that
    as "no asset link", never as an error, because a malformed row in a tool
    import must not fail the whole import.
    """
    identity = parse(observed, default_port=default_port)
    if identity is None:
        return None
    if host_level and identity.port is not None:
        identity = AssetIdentity(
            asset_type=identity.asset_type,
            hostname=identity.hostname,
            ip=identity.ip,
            port=None,
            scheme=identity.scheme,
        )

    now = seen_at or datetime.now(timezone.utc)
    asset = (
        db.query(Asset)
        .filter(Asset.program_id == program_id, Asset.canonical_key == identity.canonical_key)
        .first()
    )
    if asset:
        asset.last_seen_at = now
        return asset

    asset = Asset(
        program_id=program_id,
        canonical_key=identity.canonical_key,
        asset_type=identity.asset_type,
        label=identity.label,
        hostname=identity.hostname,
        ip=identity.ip,
        port=identity.port,
        scheme=identity.scheme,
        source=source,
        confidence=confidence,
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(asset)
    db.flush()
    return asset


def relate(
    db: Session,
    program_id: str,
    src: Asset,
    dst: Asset,
    relationship: str,
    *,
    source: str = "",
    confidence: str = "confirmed",
    seen_at: Optional[datetime] = None,
) -> Optional[AssetRelationship]:
    """Create the edge if it does not exist, else refresh last_seen_at.

    Self-edges are refused: an asset related to itself carries no information
    and makes traversal cycles trivial to hit.
    """
    if src is None or dst is None or src.id == dst.id:
        return None

    now = seen_at or datetime.now(timezone.utc)
    edge = (
        db.query(AssetRelationship)
        .filter(
            AssetRelationship.src_asset_id == src.id,
            AssetRelationship.dst_asset_id == dst.id,
            AssetRelationship.relationship == relationship,
        )
        .first()
    )
    if edge:
        edge.last_seen_at = now
        return edge

    edge = AssetRelationship(
        program_id=program_id,
        src_asset_id=src.id,
        dst_asset_id=dst.id,
        relationship=relationship,
        source=source,
        confidence=confidence,
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(edge)
    db.flush()
    return edge


def parent_domain(db: Session, program_id: str, asset: Asset) -> Optional[Asset]:
    """The registrable-ish parent of a subdomain, if it is already known.

    Deliberately does not use a public-suffix list: without one we cannot tell
    `co.uk` from `acme.com`, so we only ever link to a parent that already
    exists as an asset in this engagement. That yields no false parents.
    """
    if asset.asset_type != DOMAIN or not asset.hostname:
        return None
    parts = asset.hostname.split(".")
    for i in range(1, len(parts) - 1):
        candidate = ".".join(parts[i:])
        parent = (
            db.query(Asset)
            .filter(
                Asset.program_id == program_id,
                Asset.canonical_key == f"{DOMAIN}:{candidate}",
            )
            .first()
        )
        if parent:
            return parent
    return None
