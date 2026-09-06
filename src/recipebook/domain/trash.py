"""The trash bin, and what "delete forever" is allowed to mean.

Deleting a recipe never removes its row. There are two steps and both are
timestamps on the row itself:

  deleted_at   in the trash: gone from the index and search, listed in the
               trash bin, restorable in one press
  purged_at    deleted forever: gone from every screen there is

Even a purge keeps the row, because `recipes.parent_id` points at it. A real
DELETE would null out the link from every variant of that recipe, and a variant
that can no longer say where it came from has lost something the trash was
never asked to take. So a purged row survives as an anchor: the link stays in
the database, and the interface stops drawing it.

Deleting a recipe moves only that recipe. Its variants stay in the bank and
show their parent as deleted — a single press must never remove recipes nobody
pointed at.
"""

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.orm import Session

from recipebook.models import Recipe


class TrashRefused(Exception):
    """The recipe is not in the state that action needs, worded for the cook."""


# The index, search, category lists, and variant lists: everything that means
# "the bank".
IN_BANK: ColumnElement[bool] = Recipe.deleted_at.is_(None)

# The trash bin, and nowhere else.
IN_TRASH: ColumnElement[bool] = and_(Recipe.deleted_at.is_not(None), Recipe.purged_at.is_(None))

# Reachable in the interface at all — a purged recipe is not, anywhere.
IS_VISIBLE: ColumnElement[bool] = Recipe.purged_at.is_(None)


def visible(session: Session, recipe_id: uuid.UUID) -> Recipe | None:
    """The recipe, unless it has been purged.

    A purged row exists only to keep a variant's parent link resolvable. It has
    no page, so every route treats it exactly as it treats an id that was never
    there.
    """
    recipe = session.get(Recipe, recipe_id)
    if recipe is None or recipe.is_purged:
        return None
    return recipe


def move_to_trash(session: Session, recipe: Recipe) -> None:
    """Delete, in the sense the button means it.

    No confirmation, because this is reversible and the confirmation shield on
    the index is where the reversing happens. Variants are left where they are.
    """
    if recipe.deleted_at is not None:
        raise TrashRefused("That recipe is already in the trash.")
    recipe.deleted_at = datetime.now(UTC)


def restore(session: Session, recipe: Recipe) -> None:
    """Put it back in the bank, exactly as it was.

    A restored recipe keeps its parent link even if that parent is itself in
    the trash: the lineage is a fact about the recipe, not about what is
    currently on screen.
    """
    if recipe.deleted_at is None:
        raise TrashRefused("That recipe is not in the trash.")
    if recipe.is_purged:
        raise TrashRefused("That recipe has been deleted forever and cannot be restored.")
    recipe.deleted_at = None


def purge(session: Session, recipe: Recipe) -> None:
    """Delete forever — from the interface. The row stays.

    Going through the trash first is enforced here and by a CHECK constraint,
    so nothing can become invisible without ever having been listed somewhere
    it could be taken back from.
    """
    if recipe.deleted_at is None:
        raise TrashRefused("Put that recipe in the trash before deleting it forever.")
    if recipe.is_purged:
        raise TrashRefused("That recipe has already been deleted forever.")
    recipe.purged_at = datetime.now(UTC)


def trashed(session: Session) -> list[Recipe]:
    """What the trash bin lists: most recently deleted first."""
    return list(session.scalars(select(Recipe).where(IN_TRASH).order_by(Recipe.deleted_at.desc())))


def visible_parent_ids(session: Session, recipes: Iterable[Recipe]) -> set[uuid.UUID]:
    """Of these recipes' parents, the ones the interface is allowed to mention.

    One query for a whole listing rather than one per row. A purged parent is
    absent from the result, which is how "the link is kept but no longer
    visible" is rendered: the caller finds nothing to draw.
    """
    wanted = {recipe.parent_id for recipe in recipes if recipe.parent_id is not None}
    if not wanted:
        return set()
    return set(session.scalars(select(Recipe.id).where(Recipe.id.in_(wanted), IS_VISIBLE)))
