"""add services table and api_key last_used_at

Revision ID: 0007servicesapikey
Revises: 0006addjobeevents
Create Date: 2026-06-11

Adds:
  - services table: nmap/service-discovery results per program
  - api_keys.last_used_at: stamped on every successful API key auth
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007servicesapikey"
down_revision: Union[str, None] = "0006addjobeevents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "services",
        sa.Column("id",               sa.String(),      nullable=False),
        sa.Column("program_id",       sa.String(),      nullable=False),
        sa.Column("owner_github_id",  sa.String(),      nullable=False),
        sa.Column("host",             sa.String(500),   nullable=False),
        sa.Column("port",             sa.Integer(),     nullable=False),
        sa.Column("protocol",         sa.String(10),    nullable=False, server_default="tcp"),
        sa.Column("service_name",     sa.String(100),   nullable=False, server_default=""),
        sa.Column("product",          sa.String(200),   nullable=False, server_default=""),
        sa.Column("version",          sa.String(100),   nullable=False, server_default=""),
        sa.Column("state",            sa.String(20),    nullable=False, server_default="open"),
        sa.Column("source",           sa.String(50),    nullable=False, server_default="nmap"),
        sa.Column("created_at",       sa.DateTime(),    nullable=False),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_services_program_id",      "services", ["program_id"])
    op.create_index("ix_services_owner_github_id", "services", ["owner_github_id"])

    op.add_column("api_keys", sa.Column("last_used_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("api_keys", "last_used_at")
    op.drop_index("ix_services_owner_github_id", table_name="services")
    op.drop_index("ix_services_program_id",      table_name="services")
    op.drop_table("services")
