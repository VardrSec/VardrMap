"""Add idempotency receipts for runner result uploads.

Revision ID: 0024jobreceipts
Revises: 0023apisurface
"""
from alembic import op
import sqlalchemy as sa

revision = "0024jobreceipts"
down_revision = "0023apisurface"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "job_result_receipts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("scan_items_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["scan_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_job_result_receipts_job_id"),
    )


def downgrade():
    op.drop_table("job_result_receipts")
