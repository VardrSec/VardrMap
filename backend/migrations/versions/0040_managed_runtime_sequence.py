"""Add bounded opt-in runtime sequence history without changing v1 records."""

from alembic import op
import sqlalchemy as sa

revision = "0040runtimesequence"
down_revision = "0039managedruntime"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite needs its transactional batch-copy path for CHECK constraints. Old
    # rows remain v1 (NULL max_attempts), including retained bound/retired records.
    with op.batch_alter_table("managed_runtimes") as batch:
        batch.add_column(sa.Column("max_attempts", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("active_sequence", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("retirement_receipt", sa.JSON(), nullable=True))
        batch.create_check_constraint(
            "ck_managed_runtime_v2_binding",
            "max_attempts IS NULL OR (job_id IS NULL AND contract_id IS NULL "
            "AND attempt_id IS NULL AND fence IS NULL AND contract_sha256 IS NULL "
            "AND bound_at IS NULL AND confirmed_at IS NULL)",
        )
        batch.create_check_constraint(
            "ck_managed_runtime_v2_retirement",
            "max_attempts IS NULL OR NOT retired OR (retirement_receipt IS NOT NULL "
            "AND trim(CAST(retirement_receipt AS TEXT)) <> 'null')",
        )
    op.create_table(
        "managed_runtime_attempts",
        sa.Column("runtime_id", sa.String(36), primary_key=True),
        sa.Column("runtime_sequence", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(128), nullable=False, unique=True),
        sa.Column("contract_id", sa.String(36), nullable=False, unique=True),
        sa.Column("attempt_id", sa.String(36), nullable=False),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column("contract_sha256", sa.String(64), nullable=False),
        sa.Column("bound_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("terminal_receipt", sa.JSON(), nullable=True),
        sa.Column("terminal_receipt_sha256", sa.String(64), nullable=True),
        sa.Column("native_done_sha256", sa.String(64), nullable=True),
        sa.Column("release_receipt", sa.JSON(), nullable=True),
    )


def downgrade():
    raise RuntimeError(
        "Retain runtime sequence history, release acknowledgments and physical "
        "retirement receipts; code-only rollback over v2 state is unsupported. Reconcile retained execution "
        "ownership before restoring an independently verified backup."
    )
