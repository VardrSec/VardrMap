"""add job_logs table for SSE log streaming

Revision ID: 0005addjoblogs
Revises: 0004addscanjobs
Create Date: 2026-06-10

Log lines are posted by VardrRunner during job execution and streamed
to the frontend via GET /jobs/{id}/logs/stream (SSE). Records are
deleted when the parent scan_job is deleted (CASCADE).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005addjoblogs"
down_revision: Union[str, None] = "0004addscanjobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_logs",
        sa.Column("id",         sa.Integer(),  nullable=False, autoincrement=True),
        sa.Column("job_id",     sa.String(),   nullable=False),
        sa.Column("kind",       sa.String(10), nullable=False, server_default="out"),
        sa.Column("text",       sa.Text(),     nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["scan_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_logs_job_id", "job_logs", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_job_logs_job_id", table_name="job_logs")
    op.drop_table("job_logs")
