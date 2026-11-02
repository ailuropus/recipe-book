"""jobs

Adds the jobs table: a slow model call runs apart from the request that asked
for it, and its result is written here whether or not the browser is still
waiting.

A new table with nothing to backfill. A pending revision from before this
migration has no job, and does not need one: its review page works as it
always did.

Revision ID: e2a9c4b17f60
Revises: c5f1a3e7d284
Create Date: 2026-11-02 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2a9c4b17f60"
down_revision: str | None = "c5f1a3e7d284"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("recipe_id", sa.Uuid(), nullable=True),
        sa.Column("result_doc", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("revision_id", sa.Uuid(), nullable=True),
        sa.Column("llm_call_id", sa.Uuid(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('import', 'revise')", name="ck_jobs_kind"),
        sa.CheckConstraint("status IN ('running', 'done', 'failed')", name="ck_jobs_status"),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["llm_call_id"], ["llm_calls.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_closed_at", "jobs", ["closed_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_closed_at", table_name="jobs")
    op.drop_table("jobs")
