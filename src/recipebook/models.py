"""SQLAlchemy models.

Three tables:

  recipes    — scalar metadata as columns, structured content as JSONB
  revisions  — the audit log, the undo stack, and the pending review, in one
  llm_calls  — one row per API call, with a cost snapshot
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Weighted so a hit in the title outranks a hit buried in a step. The three-arg
# jsonb_to_tsvector (with an explicit regconfig) is IMMUTABLE, which is what a
# generated column requires — verified against Postgres 17, along with the
# stemming that makes this worth doing: 'яйца' matches 'яйцо', and the query
# 'подходит' matches 'подходить' in a step.
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


class Base(DeclarativeBase):
    pass


class Recipe(Base):
    __tablename__ = "recipes"

    # UUIDs rather than serials: JSON export/import merges by id, and that has
    # to survive moving between app versions and machines.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    title: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    hands_on_min: Mapped[int] = mapped_column(Integer)
    total_min: Mapped[int] = mapped_column(Integer)
    servings: Mapped[str] = mapped_column(Text, default="")
    plan_ahead: Mapped[bool] = mapped_column(default=False)

    # A CHECK constraint rather than a Postgres ENUM type: altering an enum in
    # a migration is painful, and this is a three-value set that may grow.
    status: Mapped[str] = mapped_column(String(16), default="new")

    equipment: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    ingredients: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    notes_md: Mapped[str] = mapped_column(Text, default="")

    # Variants. SET NULL rather than CASCADE: deleting a parent must never
    # silently take its variants with it — losing a recipe is the one
    # unrecoverable outcome here.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True
    )
    variant_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    search_tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed(SEARCH_TSV_EXPRESSION, persisted=True)
    )

    parent: Mapped["Recipe | None"] = relationship(remote_side=[id], back_populates="variants")
    variants: Mapped[list["Recipe"]] = relationship(back_populates="parent")

    __table_args__ = (
        CheckConstraint("status IN ('new', 'tried', 'solid')", name="ck_recipes_status"),
        CheckConstraint("id <> parent_id", name="ck_recipes_not_own_parent"),
        Index("ix_recipes_search_tsv", "search_tsv", postgresql_using="gin"),
        Index("ix_recipes_parent_id", "parent_id"),
        Index("ix_recipes_category", "category"),
        Index("ix_recipes_status", "status"),
    )


class Revision(Base):
    """One proposed change to one recipe.

    A row exists from the moment the LLM answers, with status='pending'. No
    recipe is touched until the review is accepted. Writing the proposal down
    is what lets the review survive a page reload or a phone locking mid-scroll,
    and it produces the audit log and the undo stack as a side effect.
    """

    __tablename__ = "revisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    recipe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"))

    status: Mapped[str] = mapped_column(String(16), default="pending")

    # 'llm' for a proposal a model wrote, 'manual' for an edit typed into the
    # form. Hand edits are recorded too, so undo covers every way a recipe can
    # change rather than mysteriously skipping half of them.
    origin: Mapped[str] = mapped_column(String(16), default="llm", server_default="llm")

    # What the cook typed, verbatim: "убавь сахар и добавь корицу".
    # Empty for a hand edit, which describes itself through the diff.
    instruction: Mapped[str] = mapped_column(Text)
    # The LLM's plain-language account of what it changed.
    summary: Mapped[str] = mapped_column(Text, default="")

    # Full RecipeDoc on both sides. Undo restores before_snapshot; the diff is
    # rendered from the pair.
    before_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    after_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)

    applied_as: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # For 'variant', the child that was created; for 'replace', the recipe itself.
    result_recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'applied', 'discarded')", name="ck_revisions_status"
        ),
        CheckConstraint("origin IN ('llm', 'manual')", name="ck_revisions_origin"),
        CheckConstraint(
            "applied_as IS NULL OR applied_as IN ('replace', 'variant')",
            name="ck_revisions_applied_as",
        ),
        Index("ix_revisions_recipe_id", "recipe_id"),
        Index("ix_revisions_status", "status"),
    )


class LlmCall(Base):
    """One API call, with the cost worked out at the time it was made.

    The model id and cost are snapshots on purpose: published rates change, and
    a row from six months ago should still mean what it meant when written.
    """

    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # Null only for a paste-import, where the call happens before the recipe
    # exists. Every revision call carries one, so summing cost per recipe
    # answers "what has this recipe cost me to perfect".
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True
    )
    revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("revisions.id", ondelete="SET NULL"), nullable=True
    )

    kind: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(64))

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_creation_input_tokens: Mapped[int] = mapped_column(Integer, default=0)

    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("kind IN ('import', 'revise', 'ask')", name="ck_llm_calls_kind"),
        Index("ix_llm_calls_recipe_id", "recipe_id"),
        Index("ix_llm_calls_called_at", "called_at"),
    )
