"""initial schema

Revision ID: d4b31e0ccf1c
Revises:
Create Date: 2026-08-15

Generated from the models with `alembic revision --autogenerate`, then tidied.

The tsvector expression is written out here as a literal rather than imported
from recipebook.models: a migration is a frozen historical record, and one that
imported live code would silently change meaning the next time the model did.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4b31e0ccf1c"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEARCH_TSV_EXPRESSION = """
    setweight(to_tsvector('russian', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce(description, '')), 'B') ||
    setweight(
        jsonb_to_tsvector('russian', coalesce(ingredients, '[]'::jsonb), '["string"]'), 'B'
    ) ||
    setweight(
        jsonb_to_tsvector('russian', coalesce(steps, '[]'::jsonb), '["string"]'), 'C'
    ) ||
    setweight(to_tsvector('russian', coalesce(notes_md, '')), 'D')
"""


def upgrade() -> None:
    op.create_table(
        "recipes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("hands_on_min", sa.Integer(), nullable=False),
        sa.Column("total_min", sa.Integer(), nullable=False),
        sa.Column("servings", sa.Text(), nullable=False),
        sa.Column("plan_ahead", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("equipment", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ingredients", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes_md", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("variant_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_TSV_EXPRESSION, persisted=True),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('new', 'tried', 'solid')", name="ck_recipes_status"),
        sa.CheckConstraint("id <> parent_id", name="ck_recipes_not_own_parent"),
        sa.ForeignKeyConstraint(["parent_id"], ["recipes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recipes_category", "recipes", ["category"])
    op.create_index("ix_recipes_parent_id", "recipes", ["parent_id"])
    op.create_index("ix_recipes_search_tsv", "recipes", ["search_tsv"], postgresql_using="gin")
    op.create_index("ix_recipes_status", "recipes", ["status"])

    op.create_table(
        "revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipe_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("before_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("after_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("applied_as", sa.String(length=16), nullable=True),
        sa.Column("result_recipe_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "applied_as IS NULL OR applied_as IN ('replace', 'variant')",
            name="ck_revisions_applied_as",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'applied', 'discarded')", name="ck_revisions_status"
        ),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["result_recipe_id"], ["recipes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_revisions_recipe_id", "revisions", ["recipe_id"])
    op.create_index("ix_revisions_status", "revisions", ["status"])

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipe_id", sa.Uuid(), nullable=True),
        sa.Column("revision_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_input_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_creation_input_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "called_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('import', 'revise')", name="ck_llm_calls_kind"),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_calls_called_at", "llm_calls", ["called_at"])
    op.create_index("ix_llm_calls_recipe_id", "llm_calls", ["recipe_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_recipe_id", table_name="llm_calls")
    op.drop_index("ix_llm_calls_called_at", table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_index("ix_revisions_status", table_name="revisions")
    op.drop_index("ix_revisions_recipe_id", table_name="revisions")
    op.drop_table("revisions")
    op.drop_index("ix_recipes_status", table_name="recipes")
    op.drop_index("ix_recipes_search_tsv", table_name="recipes", postgresql_using="gin")
    op.drop_index("ix_recipes_parent_id", table_name="recipes")
    op.drop_index("ix_recipes_category", table_name="recipes")
    op.drop_table("recipes")
