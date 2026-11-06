"""Add inactive persistent runtime identity/history; retain every finite row.

No startup, authority creation or data deletion. Persistent reporting's proposed
longer lifetime requires a separate live owner disposition before activation.
"""

from alembic import op
import sqlalchemy as sa

revision = "0041persistentruntime"
down_revision = "0040runtimesequence"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("managed_runtimes") as batch:
        for name in ("max_attempts", "last_sequence", "active_sequence"):
            batch.alter_column(name, existing_type=sa.Integer(), type_=sa.BigInteger())
        batch.alter_column("ttl_seconds", existing_type=sa.Integer(), nullable=True)
        batch.alter_column("expires_at", existing_type=sa.DateTime(), nullable=True)
        for column in (
            sa.Column("mode", sa.String(16), nullable=True),
            sa.Column("head_sequence", sa.BigInteger(), nullable=True),
            sa.Column("idle_timeout_seconds", sa.Integer(), nullable=True),
            sa.Column("admission_snapshot", sa.JSON(), nullable=True),
            sa.Column("admission_sha256", sa.String(64), nullable=True),
            sa.Column(
                "new_work_disabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("presence_at", sa.DateTime(), nullable=True),
            sa.Column("presence", sa.JSON(), nullable=True),
        ):
            batch.add_column(column)
        batch.create_unique_constraint("uq_managed_runtime_mode", ["id", "mode"])
        batch.create_check_constraint(
            "ck_managed_runtime_mode", "mode IS NULL OR mode = 'persistent'"
        )
        batch.create_check_constraint(
            "ck_managed_runtime_persistent",
            "mode IS NULL OR (ttl_seconds IS NULL AND expires_at IS NULL "
            "AND admission_snapshot IS NOT NULL AND admission_sha256 IS NOT NULL "
            "AND ((last_sequence = 0 AND head_sequence IS NULL) "
            "OR (last_sequence > 0 AND head_sequence IS NOT NULL AND head_sequence = last_sequence)) "
            "AND last_sequence BETWEEN 0 AND 9223372036854775807 "
            "AND (active_sequence IS NULL OR (head_sequence IS NOT NULL AND active_sequence = head_sequence)) "
            "AND (max_attempts IS NULL OR max_attempts BETWEEN 1 AND 9223372036854775807) "
            "AND (idle_timeout_seconds IS NULL OR idle_timeout_seconds BETWEEN 1 AND 86400))",
        )
        batch.create_check_constraint(
            "ck_managed_runtime_legacy",
            "mode IS NOT NULL OR (ttl_seconds IS NOT NULL AND expires_at IS NOT NULL "
            "AND head_sequence IS NULL AND admission_snapshot IS NULL "
            "AND admission_sha256 IS NULL AND idle_timeout_seconds IS NULL)",
        )
        batch.drop_constraint("ck_managed_runtime_v2_binding", type_="check")
        batch.create_check_constraint(
            "ck_managed_runtime_v2_binding",
            "(mode IS NULL AND max_attempts IS NULL) OR (job_id IS NULL AND contract_id IS NULL "
            "AND attempt_id IS NULL AND fence IS NULL AND contract_sha256 IS NULL "
            "AND bound_at IS NULL AND confirmed_at IS NULL)",
        )
        batch.drop_constraint("ck_managed_runtime_v2_retirement", type_="check")
        batch.create_check_constraint(
            "ck_managed_runtime_v2_retirement",
            "(mode IS NULL AND max_attempts IS NULL) OR NOT retired OR (retirement_receipt IS NOT NULL "
            "AND trim(CAST(retirement_receipt AS TEXT)) <> 'null')",
        )
    with op.batch_alter_table("managed_runtime_attempts") as batch:
        batch.alter_column(
            "runtime_sequence", existing_type=sa.Integer(), type_=sa.BigInteger()
        )
        batch.add_column(sa.Column("runtime_mode", sa.String(16), nullable=True))
        batch.add_column(sa.Column("previous_sequence", sa.BigInteger(), nullable=True))
        batch.create_unique_constraint(
            "uq_managed_runtime_attempt_mode",
            ["runtime_id", "runtime_sequence", "runtime_mode"],
        )
        batch.create_check_constraint(
            "ck_managed_runtime_predecessor",
            "runtime_mode IS NULL OR (runtime_mode = 'persistent' "
            "AND runtime_sequence BETWEEN 1 AND 9223372036854775807 "
            "AND ((runtime_sequence = 1 AND previous_sequence IS NULL) "
            "OR (runtime_sequence > 1 AND previous_sequence IS NOT NULL AND previous_sequence = runtime_sequence - 1)))",
        )
        batch.create_foreign_key(
            "fk_managed_runtime_attempt_parent",
            "managed_runtimes",
            ["runtime_id", "runtime_mode"],
            ["id", "mode"],
            deferrable=True,
            initially="DEFERRED",
        )
    # The referenced three-column key must already exist on the ORIGINAL table
    # while Alembic copies its replacement. Keep SQLite foreign keys enabled.
    with op.batch_alter_table("managed_runtime_attempts") as batch:
        batch.create_foreign_key(
            "fk_managed_runtime_predecessor",
            "managed_runtime_attempts",
            ["runtime_id", "previous_sequence", "runtime_mode"],
            ["runtime_id", "runtime_sequence", "runtime_mode"],
            deferrable=True,
            initially="DEFERRED",
        )
    # Deferred circular references allow one atomic first-claim/head insertion.
    # NULL mode keeps legacy rows outside these additive v3 relationships.
    with op.batch_alter_table("managed_runtimes") as batch:
        for name, source in (("head", "head_sequence"), ("active", "active_sequence")):
            batch.create_foreign_key(
                "fk_managed_runtime_" + name,
                "managed_runtime_attempts",
                ["id", source, "mode"],
                ["runtime_id", "runtime_sequence", "runtime_mode"],
                deferrable=True,
                initially="DEFERRED",
            )


def downgrade():
    raise RuntimeError(
        "Retain persistent identity, predecessor history, terminal/release and retirement proofs. "
        "Code-only rollback over v3 state is unsupported; reconcile ownership before restoring "
        "an independently verified backup."
    )
