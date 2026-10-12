"""Add claim-time case snapshots, assessment summaries and evidence provenance.

Upgrade is additive; historical evidence remains unlinked and assessments unknown.
Downgrade removes ONLY these new fields and loses their recorded provenance and
assessment summaries. It does not delete existing jobs, cases or evidence.
"""

import sqlalchemy as sa
from alembic import op

revision = "0027assessments"
down_revision = "0026dalfox"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("scan_jobs") as batch:
        batch.add_column(sa.Column("case_snapshot", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("assessment", sa.JSON(), nullable=True))
    with op.batch_alter_table("evidence") as batch:
        batch.add_column(sa.Column("job_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("case_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("case_ref", sa.String(200), nullable=True))
        batch.add_column(sa.Column("identity_id", sa.String(200), nullable=True))
        batch.add_column(sa.Column("observed_outcome", sa.String(30), nullable=True))
        batch.add_column(sa.Column("expected_decision", sa.String(10), nullable=True))
        batch.create_foreign_key(
            "fk_evidence_job", "scan_jobs", ["job_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_foreign_key(
            "fk_evidence_case",
            "authorization_test_cases",
            ["case_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_evidence_job_id", ["job_id"])
        batch.create_index("ix_evidence_case_id", ["case_id"])
        batch.create_index("ix_evidence_identity_id", ["identity_id"])


def downgrade():
    with op.batch_alter_table("evidence") as batch:
        batch.drop_index("ix_evidence_identity_id")
        batch.drop_index("ix_evidence_case_id")
        batch.drop_index("ix_evidence_job_id")
        batch.drop_constraint("fk_evidence_case", type_="foreignkey")
        batch.drop_constraint("fk_evidence_job", type_="foreignkey")
        for name in (
            "expected_decision",
            "observed_outcome",
            "identity_id",
            "case_ref",
            "case_id",
            "job_id",
        ):
            batch.drop_column(name)
    with op.batch_alter_table("scan_jobs") as batch:
        batch.drop_column("assessment")
        batch.drop_column("case_snapshot")
