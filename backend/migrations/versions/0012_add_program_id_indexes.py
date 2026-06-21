"""Add program_id indexes to original resource tables

Revision ID: 0012programidindexes
Revises: 0011rbacreconscopes
Create Date: 2026-06-20

Adds indexes on program_id for tables created before index=True was standard
practice: findings, scan_items, manual_tests, reports, recon_items.
These columns are the primary BOLA filter on every list query.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0012programidindexes"
down_revision: Union[str, None] = "0011rbacreconscopes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_findings_program_id",     "findings",     ["program_id"])
    op.create_index("ix_scan_items_program_id",   "scan_items",   ["program_id"])
    op.create_index("ix_manual_tests_program_id", "manual_tests", ["program_id"])
    op.create_index("ix_reports_program_id",      "reports",      ["program_id"])
    op.create_index("ix_recon_items_program_id",  "recon_items",  ["program_id"])


def downgrade() -> None:
    op.drop_index("ix_recon_items_program_id",  table_name="recon_items")
    op.drop_index("ix_reports_program_id",      table_name="reports")
    op.drop_index("ix_manual_tests_program_id", table_name="manual_tests")
    op.drop_index("ix_scan_items_program_id",   table_name="scan_items")
    op.drop_index("ix_findings_program_id",     table_name="findings")
