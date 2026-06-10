"""add job_events table for VardrRunner lifecycle reporting

Revision ID: 0006addjobeevents
Revises: 0005runnerheartbeats
Create Date: 2026-06-10

VardrRunner posts events (started, targets_resolved, running, uploaded,
done/failed) to POST /jobs/{id}/events. The frontend polls
GET /jobs/{id}/events to stream them into the Terminal panel.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006addjobeevents"
down_revision: Union[str, None] = "0005runnerheartbeats"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_events",
        sa.Column("id",               sa.String(),     nullable=False),
        sa.Column("job_id",           sa.String(),     nullable=False),
        sa.Column("owner_github_id",  sa.String(),     nullable=False),
        sa.Column("kind",             sa.String(50),   nullable=False),
        sa.Column("text",             sa.Text(),       nullable=False, server_default=""),
        sa.Column("created_at",       sa.DateTime(),   nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["scan_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_events_job_id",          "job_events", ["job_id"])
    op.create_index("ix_job_events_owner_github_id", "job_events", ["owner_github_id"])


def downgrade() -> None:
    op.drop_index("ix_job_events_owner_github_id", table_name="job_events")
    op.drop_index("ix_job_events_job_id",          table_name="job_events")
    op.drop_table("job_events")
