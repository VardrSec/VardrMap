"""Drop the submissions table

Revision ID: 0015dropsubmissions
Revises: 0014clientsauthorizations
Create Date: 2026-08-09

The submissions tracker was a bug bounty feature: it recorded reports filed to
HackerOne/Bugcrowd and the payout each one earned. VardrMap is a penetration
testing platform now, where the deliverable is a report to a client, not a
submission to a platform's bounty queue.

This migration is destructive by intent — it deletes every submission row. The
data has no equivalent under the new model, so it is not migrated anywhere.

`downgrade()` recreates the table structure so the schema can be rolled back,
but it cannot bring the rows back. Restore from a database backup if the
history is needed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015dropsubmissions"
down_revision: Union[str, None] = "0014clientsauthorizations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_submissions_owner_github_id", table_name="submissions")
    op.drop_index("ix_submissions_program_id",      table_name="submissions")
    op.drop_table("submissions")


def downgrade() -> None:
    # Structure only. The rows dropped by upgrade() are gone for good.
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
