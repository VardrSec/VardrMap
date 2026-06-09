"""add scan_jobs table for UI-initiated job queue

Revision ID: 0004addscanjobs
Revises: 0003addapikeys
Create Date: 2026-06-09

Jobs are created by the UI and polled/executed by VardrRunner on the user's
machine. status flow: pending → running → done | failed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004addscanjobs"
down_revision: Union[str, None] = "0003addapikeys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scan_jobs",
        sa.Column("id",               sa.String(),      nullable=False),
        sa.Column("program_id",       sa.String(),      nullable=False),
        sa.Column("owner_github_id",  sa.String(),      nullable=False),
        sa.Column("tool_type",        sa.String(20),    nullable=False),
        sa.Column("target_source",    sa.String(20),    nullable=False),
        sa.Column("config",           sa.JSON(),        nullable=True),
        sa.Column("status",           sa.String(20),    nullable=True, server_default="pending"),
        sa.Column("created_at",       sa.DateTime(),    nullable=False),
        sa.Column("started_at",       sa.DateTime(),    nullable=True),
        sa.Column("completed_at",     sa.DateTime(),    nullable=True),
        sa.Column("error_message",    sa.Text(),        nullable=True),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scan_jobs_program_id",      "scan_jobs", ["program_id"])
    op.create_index("ix_scan_jobs_owner_github_id", "scan_jobs", ["owner_github_id"])


def downgrade() -> None:
    op.drop_index("ix_scan_jobs_owner_github_id", table_name="scan_jobs")
    op.drop_index("ix_scan_jobs_program_id",      table_name="scan_jobs")
    op.drop_table("scan_jobs")
