"""scheduled scans, webhook notifications, multi-runner heartbeats

Revision ID: 0010schednotify
Revises: 0009submissions
Create Date: 2026-06-12

Adds:
  - scheduled_scans table: recurring scan definitions materialized into
    scan_jobs when VardrRunner polls /jobs/pending
  - users.webhook_url + users.notify_min_severity: outbound notification settings
  - runner_heartbeats: unique key changes from owner_github_id to
    (owner_github_id, hostname) so multiple machines can report independently
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010schednotify"
down_revision: Union[str, None] = "0009submissions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheduled_scans",
        sa.Column("id",              sa.String(),    nullable=False),
        sa.Column("program_id",      sa.String(),    nullable=False),
        sa.Column("owner_github_id", sa.String(),    nullable=False),
        sa.Column("tool_type",       sa.String(20),  nullable=False),
        sa.Column("target_source",   sa.String(20),  nullable=False),
        sa.Column("config",          sa.JSON(),      nullable=True),
        sa.Column("interval",        sa.String(20),  nullable=False),
        sa.Column("enabled",         sa.Boolean(),   nullable=False, server_default=sa.true()),
        sa.Column("last_run_at",     sa.DateTime(),  nullable=True),
        sa.Column("next_run_at",     sa.DateTime(),  nullable=False),
        sa.Column("created_at",      sa.DateTime(),  nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_scheduled_scans_program_id", "scheduled_scans", ["program_id"])
    op.create_index("ix_scheduled_scans_owner_github_id", "scheduled_scans", ["owner_github_id"])

    op.add_column("users", sa.Column("webhook_url", sa.String(500), nullable=False, server_default=""))
    op.add_column("users", sa.Column("notify_min_severity", sa.String(20), nullable=False, server_default="high"))

    # Postgres auto-named the 0005 unique constraint <table>_<column>_key
    op.drop_constraint("runner_heartbeats_owner_github_id_key", "runner_heartbeats", type_="unique")
    op.create_unique_constraint(
        "uq_runner_heartbeats_owner_host", "runner_heartbeats", ["owner_github_id", "hostname"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_runner_heartbeats_owner_host", "runner_heartbeats", type_="unique")
    op.create_unique_constraint(
        "runner_heartbeats_owner_github_id_key", "runner_heartbeats", ["owner_github_id"]
    )
    op.drop_column("users", "notify_min_severity")
    op.drop_column("users", "webhook_url")
    op.drop_index("ix_scheduled_scans_owner_github_id", table_name="scheduled_scans")
    op.drop_index("ix_scheduled_scans_program_id", table_name="scheduled_scans")
    op.drop_table("scheduled_scans")
