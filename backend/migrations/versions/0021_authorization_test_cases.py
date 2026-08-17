"""Add authorization_test_cases — stored VardrGate test cases per engagement

Revision ID: 0021authztestcases
Revises: 0020assetfks
Create Date: 2026-08-16

VardrRunner has had a working `vardrgate_api_test` handler for some time, but
VardrMap could not queue one: `VardrGateConfig` requires a structured `test_case`
object and `ScanJob.config` only carries flat scalars.

This table is the first of the two pieces that close that gap. A test case is
stored once per engagement and referenced from a job by id
(`config = {"test_case_id": ...}`), so job config stays flat, one case can back
many runs, and editing a case does not require re-queueing. The spec is inlined
when the job is handed to a runner — VardrRunner needs no change.

`spec` holds VardrGate's `AuthorizationTestCase` JSON verbatim rather than being
shredded into columns: VardrGate owns that schema and is free to extend it
without a migration here.

Purely additive. No existing table is touched.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021authztestcases"
down_revision: Union[str, None] = "0020assetfks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "authorization_test_cases",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "program_id",
            sa.String(),
            sa.ForeignKey("programs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_github_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("test_case_id", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_authorization_test_cases_program_id", "authorization_test_cases", ["program_id"]
    )
    op.create_index(
        "ix_authorization_test_cases_owner_github_id",
        "authorization_test_cases",
        ["owner_github_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_authorization_test_cases_owner_github_id", table_name="authorization_test_cases"
    )
    op.drop_index("ix_authorization_test_cases_program_id", table_name="authorization_test_cases")
    op.drop_table("authorization_test_cases")
