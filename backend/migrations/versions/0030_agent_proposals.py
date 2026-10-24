"""Agent proposals: inert scope/authorization/rate changes awaiting operator approval.

The MCP server can propose a scope item, an authorization or a request-rate ceiling, but
cannot apply one. A proposal sits in this table as ``pending`` until a full-access operator
approves it in the console (VardrRunner ADR 0015). Additive; nothing else changes.
"""
from alembic import op
import sqlalchemy as sa

revision = "0030agentproposals"
down_revision = "0029dropschedules"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_proposals",
        sa.Column("id",                  sa.String(),    nullable=False),
        sa.Column("program_id",          sa.String(),    nullable=False),
        sa.Column("owner_github_id",     sa.String(),    nullable=False),
        sa.Column("proposed_by",         sa.String(200), nullable=True),
        sa.Column("kind",                sa.String(20),  nullable=False),
        sa.Column("payload",             sa.JSON(),      nullable=False),
        sa.Column("reason",              sa.Text(),      nullable=True),
        sa.Column("source",              sa.String(500), nullable=True),
        sa.Column("status",              sa.String(10),  nullable=False, server_default="pending"),
        sa.Column("applied_resource_id", sa.String(),    nullable=True),
        sa.Column("created_at",          sa.DateTime(),  nullable=True),
        sa.Column("resolved_at",         sa.DateTime(),  nullable=True),
        sa.Column("resolved_by",         sa.String(),    nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_proposals_program_id", "agent_proposals", ["program_id"])
    op.create_index("ix_agent_proposals_owner_github_id", "agent_proposals", ["owner_github_id"])


def downgrade():
    op.drop_index("ix_agent_proposals_owner_github_id", table_name="agent_proposals")
    op.drop_index("ix_agent_proposals_program_id", table_name="agent_proposals")
    op.drop_table("agent_proposals")
