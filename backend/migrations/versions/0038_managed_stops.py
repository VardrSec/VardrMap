"""Add retained managed stop receipts without altering ordinary work."""

from alembic import op
import sqlalchemy as sa

revision = "0038managedstops"
down_revision = "0037managedresults"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "managed_stops",
        sa.Column("contract_id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("attempt_id", sa.String(), nullable=False),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column("contract_sha256", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("cause", sa.String(64), nullable=False),
        sa.Column("receipt_sha256", sa.String(64), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    raise RuntimeError(
        "Retain owned stop receipts; restore a verified backup only after independent execution reconciliation."
    )
