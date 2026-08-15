"""Evidence

Revision ID: 0019evidence
Revises: 0018assetgraph
Create Date: 2026-08-15

Evidence is the most dangerous data the platform holds: a captured request that
proves a vulnerability usually also contains the credential used to reach it,
and that credential belongs to someone else's production system.

Redaction happens on write (see `redaction.py`), so the `body` column stores
already-redacted text. `content_hash` is a SHA-256 over that stored body —
integrity of the artefact as retained, not as captured, which is the only thing
we can honestly attest to.

`sensitivity` and `retention` are recorded per item so exports and future
deletion policy have something to act on.

Additive. Nothing existing is touched.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019evidence"
down_revision: Union[str, None] = "0018assetgraph"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("finding_id", sa.String(), nullable=True),
        sa.Column("asset_id", sa.String(), nullable=True),
        sa.Column("kind", sa.String(length=30), nullable=False, server_default="note"),
        sa.Column("title", sa.String(length=200), server_default=""),
        sa.Column("body", sa.Text(), server_default=""),
        sa.Column("content_hash", sa.String(length=64), server_default=""),
        sa.Column("collector", sa.String(length=100), server_default=""),
        sa.Column("source", sa.String(length=60), server_default=""),
        sa.Column("sensitivity", sa.String(length=20), server_default="internal"),
        sa.Column("retention", sa.String(length=20), server_default="engagement"),
        sa.Column("redacted", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("collected_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_program_id", "evidence", ["program_id"])
    op.create_index("ix_evidence_finding_id", "evidence", ["finding_id"])
    op.create_index("ix_evidence_asset_id", "evidence", ["asset_id"])

    if op.get_bind().dialect.name == "postgresql":
        op.create_check_constraint(
            "ck_evidence_sensitivity",
            "evidence",
            "sensitivity IN ('public', 'internal', 'confidential', 'restricted')",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("ck_evidence_sensitivity", "evidence", type_="check")
    op.drop_index("ix_evidence_asset_id", table_name="evidence")
    op.drop_index("ix_evidence_finding_id", table_name="evidence")
    op.drop_index("ix_evidence_program_id", table_name="evidence")
    op.drop_table("evidence")
