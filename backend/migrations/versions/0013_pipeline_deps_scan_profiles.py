"""Pipeline dependencies, scan-item provenance, and saved scan profiles

Revision ID: 0013pipelineprofiles
Revises: 0012programidindexes
Create Date: 2026-07-22

Three additive changes supporting the premium-automation work:

- scan_jobs.depends_on — a pipeline stage waits on another job before it becomes
  eligible in GET /jobs/pending (subfinder -> httpx -> nuclei chains).
- scan_items.job_id / recon_items already had job_id; scan_items gains it for
  job -> results provenance (which run produced this finding).
- scan_profiles — reusable saved tool + config presets per program.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013pipelineprofiles"
down_revision: Union[str, None] = "0012programidindexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scan_jobs", sa.Column("depends_on", sa.String(), nullable=True))
    op.add_column("scan_items", sa.Column("job_id", sa.String(), nullable=True))

    op.create_table(
        "scan_profiles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("program_id", sa.String(), sa.ForeignKey("programs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_github_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("tool_type", sa.String(length=20), nullable=False),
        sa.Column("target_source", sa.String(length=20), nullable=False),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_scan_profiles_program_id", "scan_profiles", ["program_id"])
    op.create_index("ix_scan_profiles_owner_github_id", "scan_profiles", ["owner_github_id"])


def downgrade() -> None:
    op.drop_index("ix_scan_profiles_owner_github_id", table_name="scan_profiles")
    op.drop_index("ix_scan_profiles_program_id", table_name="scan_profiles")
    op.drop_table("scan_profiles")
    op.drop_column("scan_items", "job_id")
    op.drop_column("scan_jobs", "depends_on")
