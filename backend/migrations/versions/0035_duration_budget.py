"""Add finite cumulative duration allocations; preserve accounting on rollback."""
from alembic import op
import sqlalchemy as sa

revision = "0035durationbudget"
down_revision = "0034targetbudget"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("programs", sa.Column("duration_limit", sa.Integer(), nullable=True))
    op.add_column("programs", sa.Column("duration_allocated", sa.Integer(), server_default="0", nullable=False))
    op.add_column("job_executions", sa.Column("duration_seconds", sa.Integer(), server_default="0", nullable=False))


def downgrade():
    raise RuntimeError("Retain duration allocations; restore a verified backup only after independently reconciling all execution fences and allocated allowances.")
