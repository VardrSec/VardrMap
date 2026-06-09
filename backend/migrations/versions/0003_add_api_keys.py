"""add api_keys table for personal access tokens

Revision ID: 0003addapikeys
Revises: 0002addcreatedat
Create Date: 2026-06-08

Opaque tokens (vmap_...) are hashed with SHA-256 before storage.
The plaintext token is shown once in the UI and never persisted.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003addapikeys"
down_revision: Union[str, None] = "0002addcreatedat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id",         sa.String(),      nullable=False),
        sa.Column("github_id",  sa.String(),      nullable=False),
        sa.Column("key_hash",   sa.String(64),    nullable=False),
        sa.Column("label",      sa.String(100),   nullable=True),
        sa.Column("created_at", sa.DateTime(),    nullable=False),
        sa.ForeignKeyConstraint(["github_id"], ["users.github_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_api_keys_github_id", "api_keys", ["github_id"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_github_id", table_name="api_keys")
    op.drop_table("api_keys")
