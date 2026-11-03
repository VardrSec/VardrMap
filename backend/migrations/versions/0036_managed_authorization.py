"""Add opt-in retained approval/issuance state; no legacy engagement migration."""

from alembic import op
import sqlalchemy as sa

revision = "0036managedauth"
down_revision = "0035durationbudget"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "scan_jobs",
        sa.Column(
            "authorization_contract_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "programs",
        sa.Column("managed_authority_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("scan_jobs", sa.Column("managed_approval_id", sa.String(300), nullable=True))
    op.create_table(
        "managed_enrollments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("api_key_id", sa.String(), nullable=False),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("principal_hash", sa.String(64), nullable=False),
        sa.Column("runner_id", sa.String(36), nullable=False),
        sa.Column("origin", sa.String(500), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("principal_hash", "runner_id", name="uq_managed_principal_runner"),
    )
    op.create_table(
        "managed_approvals",
        sa.Column("id", sa.String(300), primary_key=True),
        sa.Column("issuer", sa.String(128), nullable=False),
        sa.Column("approval_id", sa.String(128), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("enrollment_id", sa.String(), nullable=False),
        sa.Column("authorization_id", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("envelope", sa.JSON(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("authority_snapshot", sa.JSON(), nullable=False),
        sa.Column("issued", sa.Integer(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("issuer", "approval_id", name="uq_managed_approval_identity"),
    )
    op.create_index("ix_managed_approvals_job_id", "managed_approvals", ["job_id"])
    op.create_index("ix_managed_approvals_engagement_id", "managed_approvals", ["engagement_id"])
    op.create_table(
        "managed_contracts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), nullable=False, unique=True),
        sa.Column("approval_record_id", sa.String(300), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.String(), nullable=False),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column("envelope", sa.JSON(), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("approval_record_id", "ordinal", name="uq_managed_approval_ordinal"),
    )
    op.create_table(
        "managed_clock",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("observed", sa.DateTime(), nullable=False),
    )


def downgrade():
    raise RuntimeError(
        "Retain signed approval counters, contracts and clock/fences; roll back code only. Restore a verified backup only after independently reconciling all execution ownership and spent allowances."
    )
