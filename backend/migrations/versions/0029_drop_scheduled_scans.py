"""Drop scheduled_scans: recurring scans are removed.

VardrRunner runs only when invoked (Runner v0.48.0), so a schedule could only
fire when an operator ran ``vardrrunner jobs run`` — it never recurred on its
own. The feature, its endpoints and the materialization step in
``GET /jobs/pending`` are removed, and this drops the table behind them.

**Destructive.** Upgrade permanently deletes every stored schedule. Approved
explicitly by the owner on 2026-10-24. Downgrade recreates the table empty; the
deleted rows cannot be recovered from it.
"""
from alembic import op
import sqlalchemy as sa

revision = "0029dropschedules"
down_revision = "0028scopeimport"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_scheduled_scans_owner_github_id", table_name="scheduled_scans")
    op.drop_index("ix_scheduled_scans_program_id", table_name="scheduled_scans")
    op.drop_table("scheduled_scans")


def downgrade():
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
