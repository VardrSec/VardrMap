"""Retain managed result/terminal receipts; no execution activation or backfill."""

from alembic import op
import sqlalchemy as sa

revision = "0037managedresults"
down_revision = "0036managedauth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "managed_results",
        sa.Column("contract_id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("attempt_id", sa.String(), nullable=False),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column("contract_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_sha256", sa.String(64), nullable=False),
        sa.Column("case_sha256", sa.String(64), nullable=False),
        sa.Column("receipt_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_created", sa.Integer(), nullable=False),
        sa.Column("scan_items_created", sa.Integer(), nullable=False),
        sa.Column("preflight_failed", sa.Boolean(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    raise RuntimeError(
        "Retain managed evidence/completion receipts; restore a verified backup only after independent reconciliation."
    )
