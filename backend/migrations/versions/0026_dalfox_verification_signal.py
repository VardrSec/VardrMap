"""Record how a scan item was detected and how confident the scanner was.

Adds two nullable columns to ``scan_items``: ``detection_method`` and
``confidence``. Both default to an empty string, so every existing row stays
valid and nothing is rewritten.

These exist so an imported match keeps the scanner's own verification signal
instead of having it flattened into our severity. dalfox is the first source to
carry one: it reports a tier (vulnerable / reflected / ast / informational), how
it detected the issue (reflection, dom-verification, ast, oob, library) and its
own confidence. Those are three independent facts, and an operator triaging a
match needs all three — "reflected, by reflection, low confidence" is a very
different thing to act on than "vulnerable, by dom-verification, high
confidence", even where both arrive with the same severity.

Packing them into the existing free-text description would have made them
unqueryable, which defeats the point of keeping them.

Upgrade is additive. Downgrade drops all four columns and therefore loses that
signal and evidence for every row; export before rolling back.
"""
from alembic import op
import sqlalchemy as sa

revision = "0026dalfox"
down_revision = "0025workflows"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("scan_items") as batch:
        batch.add_column(sa.Column("detection_method", sa.String(40), server_default=""))
        batch.add_column(sa.Column("confidence", sa.String(20), server_default=""))
        batch.add_column(sa.Column("payload", sa.Text(), server_default=""))
        batch.add_column(sa.Column("match_evidence", sa.Text(), server_default=""))


def downgrade():
    # Data loss: the scanner's detection method and confidence are not recoverable.
    with op.batch_alter_table("scan_items") as batch:
        batch.drop_column("match_evidence")
        batch.drop_column("payload")
        batch.drop_column("confidence")
        batch.drop_column("detection_method")
