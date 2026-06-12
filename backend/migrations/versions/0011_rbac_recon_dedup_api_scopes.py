"""RBAC program members, recon dedup columns, API key scopes

Revision ID: 0011rbacreconscopes
Revises: 0010schednotify
Create Date: 2026-06-12

Adds:
  - program_members table: invited collaborators on a program
  - recon_items.first_seen_at: timestamp set once on first import, never overwritten
  - recon_items.job_id: optional link back to the scan job that produced the item
  - api_keys.scope: "full" (default) or "runner" — runner keys can only hit jobs/imports/heartbeat
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011rbacreconscopes"
down_revision: Union[str, None] = "0010schednotify"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "program_members",
        sa.Column("id",               sa.String(),    nullable=False),
        sa.Column("program_id",       sa.String(),    nullable=False),
        sa.Column("owner_github_id",  sa.String(),    nullable=False),
        sa.Column("member_github_id", sa.String(),    nullable=False),
        sa.Column("role",             sa.String(20),  nullable=False, server_default="member"),
        sa.Column("invited_at",       sa.DateTime(),  nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("program_id", "member_github_id", name="uq_program_members"),
    )
    op.create_index("ix_program_members_program_id",       "program_members", ["program_id"])
    op.create_index("ix_program_members_owner_github_id",  "program_members", ["owner_github_id"])
    op.create_index("ix_program_members_member_github_id", "program_members", ["member_github_id"])

    op.add_column("recon_items", sa.Column("first_seen_at", sa.DateTime(), nullable=True))
    op.add_column("recon_items", sa.Column("job_id",        sa.String(),   nullable=True))

    op.add_column("api_keys", sa.Column("scope", sa.String(20), nullable=False, server_default="full"))


def downgrade() -> None:
    op.drop_column("api_keys", "scope")
    op.drop_column("recon_items", "job_id")
    op.drop_column("recon_items", "first_seen_at")
    op.drop_index("ix_program_members_member_github_id", table_name="program_members")
    op.drop_index("ix_program_members_owner_github_id",  table_name="program_members")
    op.drop_index("ix_program_members_program_id",       table_name="program_members")
    op.drop_table("program_members")
