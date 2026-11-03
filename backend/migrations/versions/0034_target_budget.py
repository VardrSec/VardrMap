"""Add cumulative target accounting, without modifying legacy policy."""
from alembic import op
import sqlalchemy as sa

revision = "0034targetbudget"
down_revision = "0033concurrencybudget"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("programs", sa.Column("target_limit", sa.Integer(), nullable=True))
    op.add_column("programs", sa.Column("targets_spent", sa.Integer(), server_default="0", nullable=False))
    op.add_column("job_executions", sa.Column("target_charge", sa.Integer(), server_default="0", nullable=False))
    op.add_column("job_executions", sa.Column("target_binding", sa.JSON(), nullable=True))


def downgrade():
    raise RuntimeError("Retain target accounting; restore a verified backup only after independently reconciling all execution fences and spent allowances.")
