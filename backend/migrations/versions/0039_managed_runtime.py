"""Retain opt-in runtime admission/binding and hashed host stop-only authority."""

from alembic import op
import sqlalchemy as sa

revision = "0039managedruntime"
down_revision = "0038managedstops"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "managed_runtimes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner", sa.String(128), nullable=False),
        sa.Column("enrollment_id", sa.String(128), nullable=False),
        sa.Column("enrollment_revision", sa.Integer(), nullable=False),
        sa.Column("api_key_id", sa.String(128), nullable=False),
        sa.Column("principal_sha256", sa.String(64), nullable=False),
        sa.Column("runner_id", sa.String(36), nullable=False),
        sa.Column("origin", sa.String(500), nullable=False),
        sa.Column("identity", sa.JSON(), nullable=False),
        sa.Column("runtime_sha256", sa.String(64), nullable=False),
        sa.Column("physical_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("owner_nonce", sa.String(64), nullable=False, unique=True),
        sa.Column("capability_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("registered_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("retired", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("job_id", sa.String(128), nullable=True),
        sa.Column("contract_id", sa.String(36), nullable=True, unique=True),
        sa.Column("attempt_id", sa.String(36), nullable=True),
        sa.Column("fence", sa.Integer(), nullable=True),
        sa.Column("contract_sha256", sa.String(64), nullable=True),
        sa.Column("bound_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("report_sha256", sa.String(64), nullable=True),
    )


def downgrade():
    raise RuntimeError(
        "Retain runtime incarnations, bound attempts and stop-grant hashes; "
        "roll back code only. Reconcile retained execution ownership before "
        "restoring an independently verified backup."
    )
