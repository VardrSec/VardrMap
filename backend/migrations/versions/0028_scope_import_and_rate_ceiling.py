"""Scope severity caps and a per-engagement request-rate ceiling.

Adds two nullable, additive columns:

- ``scope_items.max_severity`` (String, default ""). Carries the per-asset
  severity cap a program publishes (HackerOne's ``max_severity``). Advisory, like
  the rest of scope — it is shown and can raise a finding warning, never blocks.
- ``programs.max_request_rate`` (Integer, nullable). The most requests per second
  the engagement allows a scan job to send. When set, the job API caps a job's
  ``rate`` for httpx/nuclei/katana/ffuf to it. NULL means no ceiling, which is the
  existing behaviour, so every current row is unchanged.

Both exist so a program's published testing rules — per-asset severity and a rate
limit — can be imported and enforced instead of being retyped by hand.

Upgrade is additive. Downgrade drops both columns and therefore loses any stored
severity caps and the rate ceiling; record them elsewhere before rolling back.
"""
from alembic import op
import sqlalchemy as sa

revision = "0028scopeimport"
down_revision = "0027assessments"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("scope_items") as batch:
        batch.add_column(sa.Column("max_severity", sa.String(20), server_default=""))
    with op.batch_alter_table("programs") as batch:
        batch.add_column(sa.Column("max_request_rate", sa.Integer(), nullable=True))


def downgrade():
    # Data loss: per-asset severity caps and the engagement rate ceiling are gone.
    with op.batch_alter_table("programs") as batch:
        batch.drop_column("max_request_rate")
    with op.batch_alter_table("scope_items") as batch:
        batch.drop_column("max_severity")
