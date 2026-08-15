"""Organizations and org membership

Revision ID: 0017organizations
Revises: 0016policyengine
Create Date: 2026-08-12

Introduces the tenant. Before this, the tenancy anchor was a GitHub user id
denormalized onto clients, scan_jobs, scheduled_scans, authorizations and
services. A teammate invited to an engagement could read its findings but not
operate its jobs, and a consulting firm could not share a client record or a
runner fleet between two people.

Additive and backfilled, never destructive:

- `organizations` and `organization_members` are new.
- `clients.org_id` and `programs.org_id` are nullable and backfilled to each
  owner's personal organization.
- `owner_github_id` is left in place on every table. Access resolution honours
  ownership, org membership, and per-engagement invitation simultaneously
  (see deps.engagement_access), so nobody loses access the moment this lands.
  Removing the legacy column is a later, separate change once no code path
  reads it.

The backfill creates one personal organization per user that owns anything,
named for the user and marked with `personal_for_github_id` so it is
identifiable and the migration is reversible.
"""
from typing import Sequence, Union
import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "0017organizations"
down_revision: Union[str, None] = "0016policyengine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("personal_for_github_id", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_organizations_personal_for_github_id", "organizations", ["personal_for_github_id"]
    )

    op.create_table(
        "organization_members",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("github_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # One row per person per org: two rows with different roles would make
        # the effective role depend on query order.
        sa.UniqueConstraint("org_id", "github_id", name="uq_org_member"),
    )
    op.create_index("ix_organization_members_org_id", "organization_members", ["org_id"])
    op.create_index("ix_organization_members_github_id", "organization_members", ["github_id"])

    op.add_column("clients", sa.Column("org_id", sa.String(), nullable=True))
    op.create_index("ix_clients_org_id", "clients", ["org_id"])

    op.add_column("programs", sa.Column("org_id", sa.String(), nullable=True))
    op.create_index("ix_programs_org_id", "programs", ["org_id"])

    # SQLite cannot ALTER TABLE ADD CONSTRAINT. Production is Postgres; tests
    # build the schema from the models, where the FK is declared. Same guard as
    # migration 0016 uses for its CHECK constraint.
    if op.get_bind().dialect.name == "postgresql":
        op.create_foreign_key("fk_clients_org", "clients", "organizations", ["org_id"], ["id"])
        op.create_foreign_key("fk_programs_org", "programs", "organizations", ["org_id"], ["id"])

    _backfill()


def _backfill() -> None:
    """Give every owner a personal org and point their rows at it."""
    bind = op.get_bind()
    now = sa.func.now()

    owners = {
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT DISTINCT owner_github_id FROM programs "
                "UNION SELECT DISTINCT owner_github_id FROM clients"
            )
        )
        if row[0]
    }

    for github_id in owners:
        org_id = str(uuid.uuid4())
        bind.execute(
            sa.text(
                "INSERT INTO organizations (id, name, personal_for_github_id, created_at) "
                "VALUES (:id, :name, :gh, :created)"
            ),
            {"id": org_id, "name": f"{github_id}'s workspace", "gh": github_id, "created": _now()},
        )
        bind.execute(
            sa.text(
                "INSERT INTO organization_members (id, org_id, github_id, role, created_at) "
                "VALUES (:id, :org, :gh, 'owner', :created)"
            ),
            {"id": str(uuid.uuid4()), "org": org_id, "gh": github_id, "created": _now()},
        )
        for table in ("programs", "clients"):
            bind.execute(
                sa.text(f"UPDATE {table} SET org_id = :org WHERE owner_github_id = :gh"),
                {"org": org_id, "gh": github_id},
            )


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def downgrade() -> None:
    """Drops the tenancy tables. No engagement or client row is lost — only the
    org pointer, which the backfill can recreate."""
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("fk_programs_org", "programs", type_="foreignkey")
        op.drop_constraint("fk_clients_org", "clients", type_="foreignkey")

    op.drop_index("ix_programs_org_id", table_name="programs")
    op.drop_column("programs", "org_id")

    op.drop_index("ix_clients_org_id", table_name="clients")
    op.drop_column("clients", "org_id")

    op.drop_index("ix_organization_members_github_id", table_name="organization_members")
    op.drop_index("ix_organization_members_org_id", table_name="organization_members")
    op.drop_table("organization_members")

    op.drop_index("ix_organizations_personal_for_github_id", table_name="organizations")
    op.drop_table("organizations")
