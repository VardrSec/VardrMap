"""Map report statuses from bounty submission outcomes to deliverable states

Revision ID: 0022reportlifecycle
Revises: 0021authztestcases
Create Date: 2026-08-17

A report is the document handed to a client, but its statuses described a bounty
platform's verdict on a submission: submitted, accepted, duplicate, informative,
resolved. Those say what someone else decided about a finding, not where the
deliverable is.

The lifecycle becomes draft -> internal_review -> final -> delivered, with
archived reachable from any state (a draft superseded before it reaches a client
still needs somewhere to go).

Mapping, and the reasoning for each:

    draft        -> draft            unchanged
    submitted    -> delivered        the report left the operator's hands
    accepted     -> delivered        terminal-positive; the client has it
    resolved     -> delivered        terminal-positive; the client has it
    duplicate    -> archived         a bounty triage outcome with no deliverable
                                     meaning — the work exists but is not a
                                     deliverable in its own right
    informative  -> archived         same

Nothing maps to internal_review or final: neither state existed before, so no
stored row can honestly claim to be in one. Operators move reports there going
forward.

**Non-destructive.** This is an UPDATE-only migration. No column, table, index or
constraint is added, altered or dropped, and no row is deleted. `reports.status`
is a plain VARCHAR(20) with no CHECK constraint, so both directions are just data.

The downgrade restores the pre-migration vocabulary as faithfully as the mapping
allows. It is lossy in one direction that cannot be avoided: delivered collapses
three former values, so downgrade sends them all to `submitted`, and archived
collapses two, so downgrade sends both to `informative`. That is recorded here
rather than discovered later. Rows written *after* this migration as
internal_review or final have no pre-migration equivalent at all and downgrade to
`draft`, which is the closest truthful statement about a report that has not been
delivered.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022reportlifecycle"
down_revision: Union[str, None] = "0021authztestcases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# old -> new
_FORWARD = {
    "submitted": "delivered",
    "accepted": "delivered",
    "resolved": "delivered",
    "duplicate": "archived",
    "informative": "archived",
}

# new -> old. Lossy where the forward map collapsed several values; see docstring.
_BACKWARD = {
    "delivered": "submitted",
    "archived": "informative",
    "internal_review": "draft",
    "final": "draft",
}


def _remap(mapping: dict[str, str]) -> None:
    reports = sa.table("reports", sa.column("status", sa.String))
    for source, target in mapping.items():
        op.execute(
            reports.update().where(reports.c.status == source).values(status=target)
        )


def upgrade() -> None:
    _remap(_FORWARD)


def downgrade() -> None:
    _remap(_BACKWARD)
