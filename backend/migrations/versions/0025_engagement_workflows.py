"""Add execution provenance, finding history, and versioned engagement deliverables.

Upgrade is additive and preserves all existing records. Downgrade removes the new
workflow history and deliverables; export them before explicitly rolling back.
"""
from alembic import op
import sqlalchemy as sa

revision = "0025workflows"
down_revision = "0024jobreceipts"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("import_records") as batch:
        batch.add_column(sa.Column("job_id", sa.String(), nullable=True))
        batch.create_foreign_key("fk_import_job", "scan_jobs", ["job_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_import_records_job_id", ["job_id"])

    op.create_table(
        "job_result_links",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("scan_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recon_id", sa.String(), sa.ForeignKey("recon_items.id", ondelete="CASCADE")),
        sa.Column("scan_id", sa.String(), sa.ForeignKey("scan_items.id", ondelete="CASCADE")),
        sa.Column("service_id", sa.String(), sa.ForeignKey("services.id", ondelete="CASCADE")),
        sa.UniqueConstraint("job_id", "recon_id", name="uq_job_recon"),
        sa.UniqueConstraint("job_id", "scan_id", name="uq_job_scan"),
        sa.UniqueConstraint("job_id", "service_id", name="uq_job_service"),
        sa.CheckConstraint(
            "(CASE WHEN recon_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN scan_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN service_id IS NULL THEN 0 ELSE 1 END) = 1", name="ck_job_result_one_target",
        ),
    )
    for column in ("job_id", "recon_id", "scan_id", "service_id"):
        op.create_index(f"ix_job_result_links_{column}", "job_result_links", [column])
    op.create_table(
        "finding_activities",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("program_id", sa.String(), sa.ForeignKey("programs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finding_id", sa.String(), sa.ForeignKey("findings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("outcome", sa.String(30)),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("program_id", "finding_id"):
        op.create_index(f"ix_finding_activities_{column}", "finding_activities", [column])
    op.create_table(
        "engagement_deliverables",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("program_id", sa.String(), sa.ForeignKey("programs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("latest_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_engagement_deliverables_program_id", "engagement_deliverables", ["program_id"])
    op.create_table(
        "deliverable_revisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("deliverable_id", sa.String(), sa.ForeignKey("engagement_deliverables.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("deliverable_id", "revision", name="uq_deliverable_revision"),
    )
    op.create_index("ix_deliverable_revisions_deliverable_id", "deliverable_revisions", ["deliverable_id"])
    # Existing findings are captured lazily, under a row lock, before their first
    # update. This avoids copying potentially sensitive legacy prose without the
    # centralized redactor and avoids an unbounded data migration at deployment.


def downgrade():
    op.drop_table("deliverable_revisions")
    op.drop_table("engagement_deliverables")
    op.drop_table("finding_activities")
    op.drop_table("job_result_links")
    with op.batch_alter_table("import_records") as batch:
        batch.drop_index("ix_import_records_job_id")
        batch.drop_constraint("fk_import_job", type_="foreignkey")
        batch.drop_column("job_id")
