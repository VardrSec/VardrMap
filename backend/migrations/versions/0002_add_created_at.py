"""add created_at to scope_items, manual_tests, reports, recon_items, scan_items, import_records

Revision ID: 0002addcreatedat
Revises: 0001baseline
Create Date: 2026-06-08

Columns are nullable so existing rows are unaffected. New rows get the
timestamp from the SQLAlchemy model default (Python-side datetime.now).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002addcreatedat"
down_revision: Union[str, None] = "0001baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = [
    "scope_items",
    "manual_tests",
    "reports",
    "recon_items",
    "scan_items",
    "import_records",
]


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("created_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "created_at")
