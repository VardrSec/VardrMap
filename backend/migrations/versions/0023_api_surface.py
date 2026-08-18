"""Add API surface and redacted HTTP exchange inventory.

Revision ID: 0023apisurface
Revises: 0022reportlifecycle
"""
from alembic import op
import sqlalchemy as sa

revision = "0023apisurface"
down_revision = "0022reportlifecycle"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_endpoints",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("asset_id", sa.String(), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("scheme", sa.String(length=10), nullable=True),
        sa.Column("host", sa.String(length=400), nullable=False),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("path_template", sa.String(length=1000), nullable=False),
        sa.Column("canonical_key", sa.String(length=1500), nullable=False),
        sa.Column("source", sa.String(length=60), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("observation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("program_id", "method", "canonical_key", name="uq_api_endpoint_operation"),
    )
    op.create_index("ix_api_endpoints_program_id", "api_endpoints", ["program_id"])
    op.create_index("ix_api_endpoints_asset_id", "api_endpoints", ["asset_id"])
    op.create_table(
        "api_exchanges",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("endpoint_id", sa.String(), nullable=False),
        sa.Column("source_tool", sa.String(length=30), nullable=True),
        sa.Column("identity_label", sa.String(length=100), nullable=True),
        sa.Column("request_headers", sa.Text(), nullable=True),
        sa.Column("request_body", sa.Text(), nullable=True),
        sa.Column("response_headers", sa.Text(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_length", sa.Integer(), nullable=True),
        sa.Column("response_mime", sa.String(length=100), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("parameter_names", sa.JSON(), nullable=True),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["endpoint_id"], ["api_endpoints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_exchanges_program_id", "api_exchanges", ["program_id"])
    op.create_index("ix_api_exchanges_endpoint_id", "api_exchanges", ["endpoint_id"])


def downgrade():
    op.drop_index("ix_api_exchanges_endpoint_id", table_name="api_exchanges")
    op.drop_index("ix_api_exchanges_program_id", table_name="api_exchanges")
    op.drop_table("api_exchanges")
    op.drop_index("ix_api_endpoints_asset_id", table_name="api_endpoints")
    op.drop_index("ix_api_endpoints_program_id", table_name="api_endpoints")
    op.drop_table("api_endpoints")
