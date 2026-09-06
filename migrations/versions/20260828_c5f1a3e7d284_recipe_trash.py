"""recipe trash

Adds recipes.deleted_at and recipes.purged_at: the trash bin, and "delete
forever" on top of it.

Neither column removes a row, and that is the point. parent_id is ON DELETE
SET NULL, so a real DELETE would take the link from every variant of that
recipe with it — a variant of a deleted parent could then no longer say where
it came from. Soft deletion keeps the link resolvable and leaves the decision
about what to show to the application.

Both are nullable with no default, so an existing bank migrates to "nothing is
deleted" without a backfill.

Revision ID: c5f1a3e7d284
Revises: 7a8656aee90a
Create Date: 2026-08-28 15:10:41.220317
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5f1a3e7d284"
down_revision: str | None = "7a8656aee90a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("recipes", sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_recipes_purged_implies_deleted",
        "recipes",
        "purged_at IS NULL OR deleted_at IS NOT NULL",
    )
    op.create_index("ix_recipes_deleted_at", "recipes", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_recipes_deleted_at", table_name="recipes")
    op.drop_constraint("ck_recipes_purged_implies_deleted", "recipes", type_="check")
    op.drop_column("recipes", "purged_at")
    op.drop_column("recipes", "deleted_at")
