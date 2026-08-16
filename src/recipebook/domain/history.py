"""Applying a decision, and taking it back.

Every way a recipe can change leaves a revision row: a model proposal the cook
accepted, and an edit typed into the form. Undo works on the most recent one
and only on that one — restoring an older snapshot would silently discard
everything done since, which is not what anybody means by undo.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from recipebook.mapping import apply_doc, doc_to_dict
from recipebook.models import Recipe, Revision
from recipebook.schemas import RecipeDoc


class UndoRefused(Exception):
    """Undo would destroy something it does not own, worded for the cook."""


def record_manual_edit(
    session: Session, recipe: Recipe, before: RecipeDoc, after: RecipeDoc
) -> Revision | None:
    """Log a hand edit as an applied revision, so undo covers it too.

    Returns None when nothing actually changed: saving a form without touching
    it should not fill the history with empty entries.
    """
    if before == after:
        return None

    revision = Revision(
        recipe_id=recipe.id,
        status="applied",
        origin="manual",
        instruction="",
        summary="",
        before_snapshot=doc_to_dict(before),
        after_snapshot=doc_to_dict(after),
        applied_as="replace",
        result_recipe_id=recipe.id,
        applied_at=datetime.now(UTC),
    )
    session.add(revision)
    return revision


def apply_as_replace(session: Session, revision: Revision, recipe: Recipe) -> Recipe:
    apply_doc(recipe, RecipeDoc.model_validate(revision.after_snapshot))
    revision.status = "applied"
    revision.applied_as = "replace"
    revision.result_recipe_id = recipe.id
    revision.applied_at = datetime.now(UTC)
    return recipe


def apply_as_variant(session: Session, revision: Revision, recipe: Recipe) -> Recipe:
    """Keep both: the original stays, the revised version becomes its child.

    The variant hangs off the recipe that was revised, not off that recipe's
    own parent, so a variant of a variant records where it actually came from.
    """
    after = RecipeDoc.model_validate(revision.after_snapshot)
    variant = apply_doc(Recipe(), after)
    variant.parent_id = recipe.id
    variant.variant_note = revision.instruction or revision.summary
    session.add(variant)
    session.flush()

    revision.status = "applied"
    revision.applied_as = "variant"
    revision.result_recipe_id = variant.id
    revision.applied_at = datetime.now(UTC)
    return variant


def latest_undoable(session: Session, recipe_id: uuid.UUID) -> Revision | None:
    """The one revision that may be undone right now, if any."""
    return session.scalars(
        select(Revision)
        .where(
            Revision.recipe_id == recipe_id,
            Revision.status == "applied",
            Revision.undone_at.is_(None),
        )
        .order_by(Revision.applied_at.desc())
        .limit(1)
    ).first()


def undo(session: Session, revision: Revision, recipe: Recipe) -> None:
    """Reverse an applied revision.

    A replace is restored from before_snapshot. A variant is reversed by
    removing the recipe the variant created — but only while that recipe is
    still exactly as this revision made it. Once it has been edited or given
    variants of its own it is somebody's work, not this revision's by-product,
    and undo refuses rather than deleting it.
    """
    if revision.status != "applied" or revision.undone_at is not None:
        raise UndoRefused("That change has already been undone.")

    newest = latest_undoable(session, revision.recipe_id)
    if newest is not None and newest.id != revision.id:
        raise UndoRefused(
            "Only the most recent change can be undone. Undo the ones after it first."
        )

    if revision.applied_as == "variant":
        _undo_variant(session, revision)
    else:
        apply_doc(recipe, RecipeDoc.model_validate(revision.before_snapshot))

    revision.undone_at = datetime.now(UTC)


def _undo_variant(session: Session, revision: Revision) -> None:
    if revision.result_recipe_id is None:
        # Already gone — the row was deleted by hand. Nothing to reverse.
        return

    variant = session.get(Recipe, revision.result_recipe_id)
    if variant is None:
        return

    if session.scalar(select(Recipe.id).where(Recipe.parent_id == variant.id)) is not None:
        raise UndoRefused(
            f"{variant.title!r} has variants of its own now. Undoing would orphan them."
        )

    if variant.updated_at > variant.created_at:
        raise UndoRefused(
            f"{variant.title!r} has been changed since it was created, "
            "so undo will not delete it. Delete it yourself if that is what you want."
        )

    session.delete(variant)
    revision.result_recipe_id = None


def history_for(session: Session, recipe_id: uuid.UUID) -> list[Revision]:
    """Everything that ever happened to this recipe, newest first."""
    return list(
        session.scalars(
            select(Revision)
            .where(Revision.recipe_id == recipe_id)
            .order_by(Revision.created_at.desc())
        )
    )
