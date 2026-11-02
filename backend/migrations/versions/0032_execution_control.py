"""Add opt-in execution ownership; no legacy jobs or engagements are migrated."""

from alembic import op
import sqlalchemy as sa

revision = "0032executioncontrol"
down_revision = "0031localauth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "job_executions",
        sa.Column(
            "job_id",
            sa.String(),
            sa.ForeignKey("scan_jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("runner_id", sa.String(36), nullable=False),
        sa.Column("origin", sa.String(500), nullable=False),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("principal_hash", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
    )


def downgrade():
    raise RuntimeError(
        "Retain execution fences; roll back code without dropping control records. "
        "If schema restoration is required, restore a verified backup only after "
        "independently reconciling all execution fences."
    )
