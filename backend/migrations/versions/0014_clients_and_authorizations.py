"""Add clients and authorizations; add engagement context to programs

Revision ID: 0014clientsauthorizations
Revises: 0013pipelineprofiles
Create Date: 2026-08-04

Introduces the two concepts that separate a professional engagement from bug
bounty work: the organisation the work is performed for, and the record of
permission to test it.

This migration is deliberately additive. No column is dropped, renamed, or made
non-nullable, so every existing row and every existing API caller keeps working
unchanged. `engagement_type` backfills to "bug_bounty" because that is what the
existing rows genuinely are — pentest work is opt-in from here, not a
retroactive relabelling of history.

`programs.client_id` is nullable on purpose: bounty programmes have no client,
the programme itself is the counterparty.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014clientsauthorizations"
down_revision: Union[str, None] = "0013pipelineprofiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_github_id", sa.String(), sa.ForeignKey("users.github_id"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("contact_name", sa.String(length=200), server_default=""),
        sa.Column("contact_email", sa.String(length=200), server_default=""),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_clients_owner_github_id", "clients", ["owner_github_id"])

    op.create_table(
        "authorizations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("program_id", sa.String(), sa.ForeignKey("programs.id"), nullable=False),
        sa.Column("owner_github_id", sa.String(), nullable=False),
        sa.Column("permits", sa.Text(), server_default=""),
        sa.Column("authorized_by", sa.String(length=200), server_default=""),
        sa.Column("authorized_at", sa.DateTime(), nullable=True),
        sa.Column("reference", sa.String(length=500), server_default=""),
        sa.Column("window_start", sa.DateTime(), nullable=True),
        sa.Column("window_end", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_authorizations_program_id", "authorizations", ["program_id"])
    op.create_index("ix_authorizations_owner_github_id", "authorizations", ["owner_github_id"])

    # Engagement context on the existing table. server_default populates the
    # rows that are already there; the SQLAlchemy model carries the same
    # defaults, so inserts made through the app agree with the database.
    op.add_column("programs", sa.Column("client_id", sa.String(), nullable=True))
    op.add_column("programs", sa.Column("engagement_type", sa.String(length=20), server_default="bug_bounty"))
    op.add_column("programs", sa.Column("engagement_status", sa.String(length=20), server_default="active"))
    op.add_column("programs", sa.Column("starts_at", sa.DateTime(), nullable=True))
    op.add_column("programs", sa.Column("ends_at", sa.DateTime(), nullable=True))
    op.create_index("ix_programs_client_id", "programs", ["client_id"])
    op.create_foreign_key("fk_programs_client_id", "programs", "clients", ["client_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_programs_client_id", "programs", type_="foreignkey")
    op.drop_index("ix_programs_client_id", table_name="programs")
    op.drop_column("programs", "ends_at")
    op.drop_column("programs", "starts_at")
    op.drop_column("programs", "engagement_status")
    op.drop_column("programs", "engagement_type")
    op.drop_column("programs", "client_id")

    op.drop_index("ix_authorizations_owner_github_id", table_name="authorizations")
    op.drop_index("ix_authorizations_program_id", table_name="authorizations")
    op.drop_table("authorizations")

    op.drop_index("ix_clients_owner_github_id", table_name="clients")
    op.drop_table("clients")
