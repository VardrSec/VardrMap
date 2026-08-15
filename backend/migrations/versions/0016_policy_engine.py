"""Stop-work switch and policy audit detail

Revision ID: 0016policyengine
Revises: 0015dropsubmissions
Create Date: 2026-08-12

Supports the central policy engine (backend/policy.py), which decides whether a
capability may run against a target for an engagement right now.

Additive only. Every column is nullable or defaulted, so existing rows and
existing API callers are unaffected and the old process can keep serving while
`start.sh` brings the new one up.

- `programs.stop_work_at` / `stop_work_reason` — the emergency brake. Null means
  not engaged, which is the pre-existing behaviour for every current row.
- `audit_logs.reason` / `detail` — a denied execution attempt is the
  security-relevant event, and the reason code is the part worth keeping.

The CHECK constraint on `authorizations.status` closes a real gap: the column
documented six states in a comment while the database accepted any string. The
constraint is added with the existing six values plus the two the policy engine
needs, so no current row can violate it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016policyengine"
down_revision: Union[str, None] = "0015dropsubmissions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_AUTH_STATUSES = ("draft", "pending", "active", "suspended", "expired", "revoked", "closed")


def upgrade() -> None:
    op.add_column("programs", sa.Column("stop_work_at", sa.DateTime(), nullable=True))
    op.add_column(
        "programs",
        sa.Column("stop_work_reason", sa.String(length=500), nullable=False, server_default=""),
    )

    op.add_column(
        "audit_logs",
        sa.Column("reason", sa.String(length=50), nullable=False, server_default=""),
    )
    op.add_column(
        "audit_logs",
        sa.Column("detail", sa.String(length=500), nullable=False, server_default=""),
    )
    # Denials are queried by engagement when reviewing what was refused and why.
    op.create_index("ix_audit_logs_program_id", "audit_logs", ["program_id"])

    # SQLite cannot ALTER TABLE ADD CONSTRAINT; tests build the schema from the
    # models instead, so the constraint is Postgres-only by design.
    if op.get_bind().dialect.name == "postgresql":
        values = ", ".join(f"'{s}'" for s in _AUTH_STATUSES)
        op.create_check_constraint(
            "ck_authorizations_status",
            "authorizations",
            f"status IN ({values})",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("ck_authorizations_status", "authorizations", type_="check")

    op.drop_index("ix_audit_logs_program_id", table_name="audit_logs")
    op.drop_column("audit_logs", "detail")
    op.drop_column("audit_logs", "reason")
    op.drop_column("programs", "stop_work_reason")
    op.drop_column("programs", "stop_work_at")
