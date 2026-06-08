"""baseline — existing schema snapshot; stamp head on live databases

Revision ID: 0001baseline
Revises:
Create Date: 2026-06-08

This is a no-op baseline migration. All tables are created by
SQLAlchemy's create_all() on fresh deployments. For any existing
deployment that was running before Alembic was wired up, run:

    alembic stamp head

That marks the database as up-to-date without touching the schema.
All future column/table changes should be incremental revisions
generated with: alembic revision --autogenerate -m "<description>"
"""
from typing import Sequence, Union

revision: str = "0001baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
