"""revision origin

Adds revisions.origin so a hand edit can be recorded alongside a model
proposal and undo can cover both.

The server_default is what makes this safe against a table that already holds
rows: every existing revision came from a model, so 'llm' is the correct value
for all of them and Postgres fills it in without a separate backfill step.

Revision ID: 0b72e04bd51a
Revises: d4b31e0ccf1c
Create Date: 2026-08-16 12:36:15.805919
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0b72e04bd51a"
down_revision: str | None = "d4b31e0ccf1c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "revisions",
        sa.Column("origin", sa.String(length=16), server_default="llm", nullable=False),
    )
    op.create_check_constraint("ck_revisions_origin", "revisions", "origin IN ('llm', 'manual')")


def downgrade() -> None:
    op.drop_constraint("ck_revisions_origin", "revisions", type_="check")
    op.drop_column("revisions", "origin")
