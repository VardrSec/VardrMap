"""radar_programs table and services.last_scanned_at

Revision ID: 0008radarservice
Revises: 0007servicesapikey
Create Date: 2026-06-11

Adds:
  - radar_programs table: program opportunities discovered from platform APIs
  - services.last_scanned_at: stamped on every nmap upsert for freshness tracking
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008radarservice"
down_revision: Union[str, None] = "0007servicesapikey"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "radar_programs",
        sa.Column("id",               sa.String(),      nullable=False),
        sa.Column("owner_github_id",  sa.String(),      nullable=False),
        sa.Column("platform",         sa.String(20),    nullable=False),
        sa.Column("platform_id",      sa.String(200),   nullable=False),
        sa.Column("name",             sa.String(300),   nullable=False),
        sa.Column("url",              sa.String(500),   nullable=False, server_default=""),
        sa.Column("max_payout",       sa.Integer(),     nullable=True),
        sa.Column("is_new",           sa.String(1),     nullable=False, server_default="1"),
        sa.Column("discovered_at",    sa.DateTime(),    nullable=False),
        sa.Column("last_fetched_at",  sa.DateTime(),    nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_radar_programs_owner_github_id", "radar_programs", ["owner_github_id"])
    op.create_index("ix_radar_programs_platform_platform_id", "radar_programs", ["platform", "platform_id"])

    op.add_column("services", sa.Column("last_scanned_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("services", "last_scanned_at")
    op.drop_index("ix_radar_programs_platform_platform_id", table_name="radar_programs")
    op.drop_index("ix_radar_programs_owner_github_id",      table_name="radar_programs")
    op.drop_table("radar_programs")
