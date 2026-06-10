"""add runner_heartbeats table for VardrRunner status reporting

Revision ID: 0005runnerheartbeats
Revises: 0004addscanjobs
Create Date: 2026-06-10

One row per user, upserted on every POST /runner/heartbeat. Stores hostname,
version, OS, tool availability, and last_seen timestamp. Frontend polls
GET /runner/status to derive online/offline state (online = last_seen < 5 min ago).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005runnerheartbeats"
down_revision: Union[str, None] = "0004addscanjobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runner_heartbeats",
        sa.Column("id",               sa.String(),      nullable=False),
        sa.Column("owner_github_id",  sa.String(),      nullable=False),
        sa.Column("hostname",         sa.String(200),   nullable=True, server_default=""),
        sa.Column("version",          sa.String(50),    nullable=True, server_default=""),
        sa.Column("os_info",          sa.String(200),   nullable=True, server_default=""),
        sa.Column("tools",            sa.JSON(),        nullable=True),
        sa.Column("last_seen",        sa.DateTime(),    nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_github_id"),
    )
    op.create_index("ix_runner_heartbeats_owner_github_id", "runner_heartbeats", ["owner_github_id"])


def downgrade() -> None:
    op.drop_index("ix_runner_heartbeats_owner_github_id", table_name="runner_heartbeats")
    op.drop_table("runner_heartbeats")
