"""Create the frozen pre-Alembic schema for fresh databases.

Revision ID: 0001baseline
Revises:

Schema copied from dc36584 (before 0002), never from current ORM models.
Already-stamped databases skip this revision. An unstamped nonempty database
must be inspected and stamped at its actual revision before upgrading.
Downgrade retains the historical baseline tables, as the original revision did.
"""

from alembic import op
import sqlalchemy as sa

revision = "0001baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not op.get_context().as_sql:
        existing = set(sa.inspect(op.get_bind()).get_table_names()) - {
            "alembic_version"
        }
        if existing:
            raise RuntimeError(
                "Nonempty unstamped database: inspect its schema and stamp its actual "
                "Alembic revision before upgrading. Do not stamp head blindly."
            )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("github_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_logs_github_id"), "audit_logs", ["github_id"], unique=False
    )
    op.create_table(
        "users",
        sa.Column("github_id", sa.String(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("github_id"),
    )
    op.create_table(
        "programs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("owner_github_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("platform", sa.String(length=80), nullable=True),
        sa.Column("program_url", sa.String(length=500), nullable=True),
        sa.Column("scope_summary", sa.Text(), nullable=True),
        sa.Column("severity_guidance", sa.Text(), nullable=True),
        sa.Column("safe_harbor_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_github_id"],
            ["users.github_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_programs_owner_github_id"),
        "programs",
        ["owner_github_id"],
        unique=False,
    )
    op.create_table(
        "findings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=True),
        sa.Column("asset", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("steps", sa.Text(), nullable=True),
        sa.Column("impact", sa.Text(), nullable=True),
        sa.Column("remediation", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "import_records",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("tool_type", sa.String(length=20), nullable=True),
        sa.Column("filename", sa.String(length=200), nullable=True),
        sa.Column("imported_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "manual_tests",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "recon_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("host", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("webserver", sa.String(length=200), nullable=True),
        sa.Column("port", sa.String(length=10), nullable=True),
        sa.Column("tech", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(length=200), nullable=True),
        sa.Column("length", sa.Integer(), nullable=True),
        sa.Column("words", sa.Integer(), nullable=True),
        sa.Column("lines", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "reports",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("finding_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("steps", sa.Text(), nullable=True),
        sa.Column("impact", sa.Text(), nullable=True),
        sa.Column("remediation", sa.Text(), nullable=True),
        sa.Column("cwe", sa.String(length=50), nullable=True),
        sa.Column("cvss", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "scan_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=True),
        sa.Column("template_id", sa.String(length=200), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=True),
        sa.Column("asset", sa.Text(), nullable=True),
        sa.Column("matched_at", sa.Text(), nullable=True),
        sa.Column("type", sa.String(length=50), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("cwe", sa.String(length=50), nullable=True),
        sa.Column("cvss", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "scope_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("scope_type", sa.String(length=3), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    # Baseline rollback has always retained the pre-Alembic tables.
    pass
