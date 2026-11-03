"""Explicit engagement capacity; retain accounting on code rollback."""
from alembic import op
import sqlalchemy as sa

revision = "0033concurrencybudget"
down_revision = "0032executioncontrol"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("programs", sa.Column("concurrency_limit", sa.Integer(), nullable=True))
    op.add_column("job_executions", sa.Column("capacity_reserved", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade():
    raise RuntimeError("Retain budget reservations; restore a verified backup only after independently reconciling all owned execution fences.")
