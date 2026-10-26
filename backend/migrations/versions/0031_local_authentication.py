"""Add local credentials and revocable sessions without changing existing identities."""

from alembic import op
import sqlalchemy as sa

revision = "0031localauth"
down_revision = "0030agentproposals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "local_bootstrap",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.CheckConstraint("id = 1", name="ck_local_bootstrap_singleton"),
    )
    op.create_table(
        "local_credentials",
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.github_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_failure_at", sa.DateTime(), nullable=True),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "local_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("local_credentials.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_local_sessions_user_id", "local_sessions", ["user_id"])
    op.create_index("ix_local_sessions_expires_at", "local_sessions", ["expires_at"])


def downgrade():
    raise RuntimeError(
        "Local authentication downgrade deletes credentials/sessions; restore a verified backup instead"
    )
