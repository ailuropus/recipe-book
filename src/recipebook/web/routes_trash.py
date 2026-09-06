"""Delete, restore, delete forever, and the bin they all pass through.

Deleting is one press with no confirmation dialog, which is only defensible
because it is reversible: the recipe lands in the trash, the index that follows
carries a shield offering it straight back, and the trash bin keeps it after
the shield is gone.

Where a decision lands afterwards is decided here, from a fixed set of names —
never from a URL in the request. There is no redirect this app takes from the
outside.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from recipebook.db import session_scope
from recipebook.domain.trash import (
    TrashRefused,
    move_to_trash,
    purge,
    restore,
    trashed,
    visible,
)
from recipebook.models import Recipe
from recipebook.web.responses import see_other
from recipebook.web.templating import build_templates

router = APIRouter()
templates = build_templates()

SessionDep = Annotated[Session, Depends(session_scope)]

# Every place a restore can be pressed from, and nowhere else. Anything not
# named here falls back to the recipe's own page.
RETURN_TO = {"index": "/", "trash": "/trash"}


def _get_recipe(session: Session, recipe_id: uuid.UUID) -> Recipe:
    recipe = visible(session, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="No such recipe")
    return recipe


@router.get("/trash", response_class=HTMLResponse)
def trash_index(request: Request, session: SessionDep) -> HTMLResponse:
    """What has been deleted, newest first.

    Nothing expires on a timer. A recipe leaves this list because you restored
    it or because you said forever, and never because a fortnight passed.
    """
    return templates.TemplateResponse(request, "trash.html", {"recipes": trashed(session)})


@router.post("/recipes/{recipe_id}/delete")
def delete_recipe(session: SessionDep, recipe_id: uuid.UUID) -> Response:
    recipe = _get_recipe(session, recipe_id)

    try:
        move_to_trash(session, recipe)
    except TrashRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # The index, carrying the shield. The recipe's own page would be a page
    # about something that is no longer in the bank.
    return see_other(session, f"/?deleted={recipe.id}")


@router.post("/recipes/{recipe_id}/restore")
def restore_recipe(
    session: SessionDep,
    recipe_id: uuid.UUID,
    back: Annotated[str, Form()] = "",
) -> Response:
    recipe = _get_recipe(session, recipe_id)

    try:
        restore(session, recipe)
    except TrashRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return see_other(session, RETURN_TO.get(back, f"/recipes/{recipe.id}"))


@router.post("/recipes/{recipe_id}/purge")
def purge_recipe(session: SessionDep, recipe_id: uuid.UUID) -> Response:
    recipe = _get_recipe(session, recipe_id)

    try:
        purge(session, recipe)
    except TrashRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Always the bin: whichever screen this was pressed from, the recipe's page
    # has just stopped existing.
    return see_other(session, "/trash")
