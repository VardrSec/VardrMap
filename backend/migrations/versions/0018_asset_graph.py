"""Asset graph

Revision ID: 0018assetgraph
Revises: 0017organizations
Create Date: 2026-08-12

Gives the attack surface a spine.

Before this, a host existed as five unrelated free-text columns —
`recon_items.host`, `recon_items.url`, `services.host`, `scan_items.asset`,
`findings.asset` — with no foreign key between them. Identity resolution was
string comparison, so `api.acme.com`, `https://api.acme.com/` and
`api.acme.com:443` were three different things. A finding could not be traced
to the service that exposed it, risk could not be aggregated per host, and
attack surface could not be diffed over time.

`assets` is the node table, keyed by `canonical_key` (unique per engagement).
`asset_relationships` is the edge table. The four observation tables gain a
nullable `asset_id`.

## Backfill and its one irreversible risk

Existing rows are read and their host strings normalized through the same
function the application uses (`assets.parse`). Two rows that normalize to the
same key **converge onto one asset** — that is the point, and it is also the
one thing this migration cannot undo, because after the merge there is no record
of which rows were distinct beforehand.

The normalizer is deliberately conservative: anything it cannot classify is left
with `asset_id = NULL` rather than forced into a bucket. A NULL link is
recoverable later; a wrong merge is not.

`downgrade()` drops both tables and the four columns. No observation row is
lost — only the links, which a re-run of the backfill reconstructs.
"""
from typing import Sequence, Union
import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "0018assetgraph"
down_revision: Union[str, None] = "0017organizations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("canonical_key", sa.String(length=600), nullable=False),
        sa.Column("asset_type", sa.String(length=40), nullable=False, server_default="domain"),
        sa.Column("label", sa.String(length=500), server_default=""),
        sa.Column("hostname", sa.String(length=400), server_default=""),
        sa.Column("ip", sa.String(length=60), server_default=""),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("scheme", sa.String(length=20), server_default=""),
        sa.Column("environment", sa.String(length=40), server_default=""),
        sa.Column("criticality", sa.String(length=20), server_default=""),
        sa.Column("exposure", sa.String(length=20), server_default=""),
        sa.Column("owner_note", sa.String(length=200), server_default=""),
        sa.Column("tags", sa.String(length=500), server_default=""),
        sa.Column("source", sa.String(length=60), server_default=""),
        sa.Column("confidence", sa.String(length=20), server_default="confirmed"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("program_id", "canonical_key", name="uq_asset_canonical"),
    )
    op.create_index("ix_assets_program_id", "assets", ["program_id"])
    op.create_index("ix_assets_hostname", "assets", ["hostname"])
    op.create_index("ix_assets_ip", "assets", ["ip"])

    op.create_table(
        "asset_relationships",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("src_asset_id", sa.String(), nullable=False),
        sa.Column("dst_asset_id", sa.String(), nullable=False),
        sa.Column("relationship", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=60), server_default=""),
        sa.Column("confidence", sa.String(length=20), server_default="confirmed"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["src_asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dst_asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("src_asset_id", "dst_asset_id", "relationship", name="uq_asset_edge"),
    )
    op.create_index("ix_asset_rel_program_id", "asset_relationships", ["program_id"])
    op.create_index("ix_asset_rel_src", "asset_relationships", ["src_asset_id"])
    op.create_index("ix_asset_rel_dst", "asset_relationships", ["dst_asset_id"])

    for table in ("recon_items", "scan_items", "services", "findings"):
        op.add_column(table, sa.Column("asset_id", sa.String(), nullable=True))
        op.create_index(f"ix_{table}_asset_id", table, ["asset_id"])

    _backfill()


def _backfill() -> None:
    """Resolve every existing observation to an asset. Unparseable stays NULL."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from dataclasses import replace  # noqa: E402

    from assets import parse  # noqa: E402  — needs the path above

    bind = op.get_bind()
    now = _now()

    # (table, column expression preferred first)
    sources = [
        ("recon_items", ["url", "host"]),
        ("scan_items", ["asset", "matched_at"]),
        ("services", ["host"]),
        ("findings", ["asset"]),
    ]

    cache: dict[tuple[str, str], str] = {}

    for table, columns in sources:
        cols = ", ".join(columns)
        rows = bind.execute(sa.text(f"SELECT id, program_id, {cols} FROM {table}")).fetchall()
        for row in rows:
            row_id, program_id = row[0], row[1]
            observed = next((v for v in row[2:] if v), None)
            if not observed or not program_id:
                continue
            # Host level: a finding on `api.acme.com` and a recon row on
            # `https://api.acme.com/v1` are the same thing. Linking them to
            # different nodes would leave the graph as fragmented as the
            # free-text columns it replaces.
            identity = parse(observed)
            if identity is not None and identity.port is not None:
                identity = replace(identity, port=None)
            if identity is None:
                continue  # unclassifiable stays unlinked — recoverable later

            key = (program_id, identity.canonical_key)
            asset_id = cache.get(key)
            if asset_id is None:
                existing = bind.execute(
                    sa.text(
                        "SELECT id FROM assets WHERE program_id = :p AND canonical_key = :k"
                    ),
                    {"p": program_id, "k": identity.canonical_key},
                ).fetchone()
                if existing:
                    asset_id = existing[0]
                else:
                    asset_id = str(uuid.uuid4())
                    bind.execute(
                        sa.text(
                            "INSERT INTO assets (id, program_id, canonical_key, asset_type, "
                            "label, hostname, ip, port, scheme, source, confidence, "
                            "first_seen_at, last_seen_at, created_at) VALUES "
                            "(:id, :p, :k, :t, :l, :h, :ip, :port, :s, 'backfill', 'confirmed', "
                            ":now, :now, :now)"
                        ),
                        {
                            "id": asset_id, "p": program_id, "k": identity.canonical_key,
                            "t": identity.asset_type, "l": identity.label,
                            "h": identity.hostname, "ip": identity.ip,
                            "port": identity.port, "s": identity.scheme, "now": now,
                        },
                    )
                cache[key] = asset_id

            bind.execute(
                sa.text(f"UPDATE {table} SET asset_id = :a WHERE id = :i"),
                {"a": asset_id, "i": row_id},
            )


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def downgrade() -> None:
    for table in ("recon_items", "scan_items", "services", "findings"):
        op.drop_index(f"ix_{table}_asset_id", table_name=table)
        op.drop_column(table, "asset_id")

    op.drop_index("ix_asset_rel_dst", table_name="asset_relationships")
    op.drop_index("ix_asset_rel_src", table_name="asset_relationships")
    op.drop_index("ix_asset_rel_program_id", table_name="asset_relationships")
    op.drop_table("asset_relationships")

    op.drop_index("ix_assets_ip", table_name="assets")
    op.drop_index("ix_assets_hostname", table_name="assets")
    op.drop_index("ix_assets_program_id", table_name="assets")
    op.drop_table("assets")
