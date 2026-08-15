"""Add the asset_id foreign keys migration 0018 declared but never created

Revision ID: 0020assetfks
Revises: 0019evidence
Create Date: 2026-08-15

Migration 0018 added four `asset_id` columns and the ORM declares them as
foreign keys with ON DELETE SET NULL — but the migration never issued
`create_foreign_key`, so production Postgres has plain string columns.

The gap is not cosmetic. Without the constraint the database will not enforce
referential integrity, and `ON DELETE SET NULL` never fires: deleting an asset
leaves recon rows, scan rows, services and findings pointing at an id that no
longer exists, and every join through it silently returns nothing. The ORM
believes one thing and the database does another.

Orphaned references are cleared before the constraints are added, because a row
pointing at a missing asset would otherwise abort the ALTER.

Postgres only — SQLite cannot ALTER TABLE ADD CONSTRAINT, and tests build the
schema from the models where the FKs are already declared.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020assetfks"
down_revision: Union[str, None] = "0019evidence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("recon_items", "scan_items", "services", "findings")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    bind = op.get_bind()
    for table in _TABLES:
        # Clear references to assets that no longer exist; the ALTER would
        # otherwise fail on the first orphan.
        bind.execute(
            sa.text(
                f"UPDATE {table} SET asset_id = NULL WHERE asset_id IS NOT NULL "
                f"AND asset_id NOT IN (SELECT id FROM assets)"
            )
        )
        op.create_foreign_key(
            f"fk_{table}_asset_id", table, "assets", ["asset_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in _TABLES:
        op.drop_constraint(f"fk_{table}_asset_id", table, type_="foreignkey")
