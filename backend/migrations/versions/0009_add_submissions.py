"""submissions table

Revision ID: 0009submissions
Revises: 0008radarservice
Create Date: 2026-06-11

Adds:
  - submissions table: tracks bug bounty report lifecycle (submitted → paid/rejected)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009submissions"
down_revision: Union[str, None] = "0008radarservice"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "submissions",
        sa.Column("id",                 sa.String(),      nullable=False),
        sa.Column("program_id",         sa.String(),      nullable=False),
        sa.Column("owner_github_id",    sa.String(),      nullable=False),
        sa.Column("finding_id",         sa.String(),      nullable=False, server_default=""),
        sa.Column("report_id",          sa.String(),      nullable=False, server_default=""),
        sa.Column("platform",           sa.String(50),    nullable=False, server_default=""),
        sa.Column("platform_reference", sa.String(200),   nullable=False, server_default=""),
        sa.Column("title",              sa.String(200),   nullable=False, server_default=""),
        sa.Column("status",             sa.String(30),    nullable=False, server_default="submitted"),
        sa.Column("payout_usd",         sa.Float(),       nullable=True),
        sa.Column("severity",           sa.String(20),    nullable=False, server_default=""),
        sa.Column("submitted_at",       sa.DateTime(),    nullable=True),
        sa.Column("resolved_at",        sa.DateTime(),    nullable=True),
        sa.Column("notes",              sa.Text(),        nullable=False, server_default=""),
        sa.Column("created_at",         sa.DateTime(),    nullable=False),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_submissions_program_id",      "submissions", ["program_id"])
    op.create_index("ix_submissions_owner_github_id", "submissions", ["owner_github_id"])


def downgrade() -> None:
    op.drop_index("ix_submissions_owner_github_id", table_name="submissions")
    op.drop_index("ix_submissions_program_id",      table_name="submissions")
    op.drop_table("submissions")
