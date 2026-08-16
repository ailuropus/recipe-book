"""The whole recipe bank as one JSON document.

This is the file that outlives the app. It carries ids and lineage, unlike a
RecipeDoc, because the point is to be able to restore a bank onto a fresh
database — or a later version of this app — and get the same recipes back with
the same links between them.

Deliberately not included: revisions and llm_calls. Those are the history of
how a recipe got here, not the recipe. Keeping them out means an export stays
small, and an import can never resurrect a pending review.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from recipebook.mapping import apply_doc, doc_from_recipe
from recipebook.models import Recipe
from recipebook.schemas import RecipeDoc

# Bumped only when the file layout changes in a way an older reader would get
# wrong. The recipe body is validated by RecipeDoc, which has its own rules.
FORMAT_VERSION = 1


class PortableRecipe(RecipeDoc):
    """A recipe plus the identity a document deliberately leaves out."""

    id: uuid.UUID
    parent_id: uuid.UUID | None = None
    variant_note: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Export(BaseModel):
    format_version: int = FORMAT_VERSION
    exported_at: datetime
    recipes: list[PortableRecipe] = Field(default_factory=list)


@dataclass(frozen=True)
class ImportReport:
    added: int
    updated: int
    skipped: int
    relinked: int

    def __str__(self) -> str:
        parts = [f"{self.added} added", f"{self.updated} updated", f"{self.skipped} unchanged"]
        if self.relinked:
            parts.append(f"{self.relinked} parent link(s) deferred and resolved")
        return ", ".join(parts)


MergeMode = Literal["merge", "replace"]


def export_all(session: Session) -> Export:
    """Every recipe, parents before children.

    The order is not required by the importer — it resolves forward references
    on a second pass — but it makes the file readable and makes a hand-edited
    one more likely to load first time.
    """
    recipes = list(session.scalars(select(Recipe).order_by(Recipe.created_at, Recipe.title)))
    ordered = _parents_first(recipes)

    return Export(
        exported_at=datetime.now(UTC),
        recipes=[_to_portable(recipe) for recipe in ordered],
    )


def _parents_first(recipes: list[Recipe]) -> list[Recipe]:
    by_id = {recipe.id: recipe for recipe in recipes}
    seen: set[uuid.UUID] = set()
    ordered: list[Recipe] = []

    def visit(recipe: Recipe, guard: frozenset[uuid.UUID]) -> None:
        if recipe.id in seen or recipe.id in guard:
            # The guard also stops a parent cycle, which the database permits
            # across two rows even though it forbids a recipe being its own
            # parent. An export must not hang on bad data.
            return
        parent = by_id.get(recipe.parent_id) if recipe.parent_id else None
        if parent is not None:
            visit(parent, guard | {recipe.id})
        if recipe.id not in seen:
            seen.add(recipe.id)
            ordered.append(recipe)

    for recipe in recipes:
        visit(recipe, frozenset())
    return ordered


def _to_portable(recipe: Recipe) -> PortableRecipe:
    return PortableRecipe(
        **doc_from_recipe(recipe).model_dump(),
        id=recipe.id,
        parent_id=recipe.parent_id,
        variant_note=recipe.variant_note,
        created_at=recipe.created_at,
        updated_at=recipe.updated_at,
    )


def export_json(session: Session, *, indent: int = 2) -> str:
    return export_all(session).model_dump_json(indent=indent) + "\n"


def parse_export(payload: str | bytes) -> Export:
    export = Export.model_validate_json(payload)
    if export.format_version > FORMAT_VERSION:
        raise ValueError(
            f"That file is format version {export.format_version}, and this app "
            f"understands up to {FORMAT_VERSION}. Use a newer version to read it."
        )
    return export


def import_export(session: Session, export: Export, *, mode: MergeMode = "merge") -> ImportReport:
    """Merge recipes in by id.

    'merge' leaves anything not mentioned in the file alone; 'replace' deletes
    it. Merge is the default because an import is usually a restore or a
    migration between app versions, and quietly deleting recipes the file
    happens not to mention is the worst thing this function could do.

    Parent links are applied on a second pass, so a file whose children come
    before their parents still loads.
    """
    incoming = {portable.id: portable for portable in export.recipes}
    existing = {
        recipe.id: recipe
        for recipe in session.scalars(select(Recipe).where(Recipe.id.in_(incoming.keys())))
    }

    added = updated = skipped = 0
    deferred = 0

    for portable in export.recipes:
        recipe = existing.get(portable.id)
        if recipe is None:
            recipe = Recipe(id=portable.id)
            session.add(recipe)
            existing[portable.id] = recipe
            added += 1
        elif _content_of(recipe) == _document_of(portable) and _lineage_matches(recipe, portable):
            skipped += 1
            continue
        else:
            updated += 1

        apply_doc(recipe, _document_of(portable))
        recipe.variant_note = portable.variant_note
        if portable.created_at is not None:
            recipe.created_at = portable.created_at

    session.flush()

    # Second pass: every row now exists, so a parent link cannot fail on a
    # child that appeared first in the file.
    for portable in export.recipes:
        recipe = existing[portable.id]
        parent_id = portable.parent_id
        # A parent that is neither in this file nor already in the database:
        # drop the link rather than fail the whole import. An orphaned variant
        # is recoverable; a refused restore is not.
        if (
            parent_id is not None
            and parent_id not in existing
            and session.get(Recipe, parent_id) is None
        ):
            parent_id = None
        if recipe.parent_id != parent_id:
            deferred += 1
        recipe.parent_id = parent_id

    if mode == "replace":
        for recipe in session.scalars(select(Recipe)):
            if recipe.id not in incoming:
                session.delete(recipe)

    session.flush()
    return ImportReport(added=added, updated=updated, skipped=skipped, relinked=deferred)


def _document_of(portable: PortableRecipe) -> RecipeDoc:
    return RecipeDoc.model_validate(
        portable.model_dump(exclude={"id", "parent_id", "variant_note", "created_at", "updated_at"})
    )


def _content_of(recipe: Recipe) -> RecipeDoc:
    return doc_from_recipe(recipe)


def _lineage_matches(recipe: Recipe, portable: PortableRecipe) -> bool:
    return recipe.parent_id == portable.parent_id and recipe.variant_note == portable.variant_note


def json_default(value: Any) -> str:
    if isinstance(value, uuid.UUID | datetime):
        return str(value)
    raise TypeError(f"Not JSON-serialisable: {type(value)!r}")
