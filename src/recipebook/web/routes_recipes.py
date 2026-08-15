"""Index, detail, and the plain edit form."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from recipebook.db import session_scope
from recipebook.models import Recipe
from recipebook.web.templating import build_templates

router = APIRouter()
templates = build_templates()

SessionDep = Annotated[Session, Depends(session_scope)]


def _get_recipe(session: Session, recipe_id: uuid.UUID) -> Recipe:
    recipe = session.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="No such recipe")
    return recipe


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    session: SessionDep,
    q: Annotated[str, Query()] = "",
    category: Annotated[str, Query()] = "",
    status: Annotated[str, Query()] = "",
) -> HTMLResponse:
    statement = select(Recipe)

    if q.strip():
        # plainto_tsquery with the 'russian' config, so a search for "яйца"
        # finds a recipe that says "яйцо". Ranked, so a title hit beats a hit
        # buried in a step.
        statement = statement.where(text("search_tsv @@ plainto_tsquery('russian', :q)")).order_by(
            text("ts_rank(search_tsv, plainto_tsquery('russian', :q)) DESC")
        )
        statement = statement.params(q=q.strip())
    else:
        statement = statement.order_by(Recipe.title)

    if category.strip():
        statement = statement.where(Recipe.category == category.strip())
    if status.strip():
        statement = statement.where(Recipe.status == status.strip())

    recipes = list(session.scalars(statement))

    categories = list(session.scalars(select(Recipe.category).distinct().order_by(Recipe.category)))

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "recipes": recipes,
            "categories": categories,
            "q": q,
            "active_category": category,
            "active_status": status,
        },
    )


@router.get("/recipes/{recipe_id}", response_class=HTMLResponse)
def detail(request: Request, session: SessionDep, recipe_id: uuid.UUID) -> HTMLResponse:
    recipe = _get_recipe(session, recipe_id)

    variants = list(
        session.scalars(select(Recipe).where(Recipe.parent_id == recipe.id).order_by(Recipe.title))
    )
    parent = session.get(Recipe, recipe.parent_id) if recipe.parent_id else None

    return templates.TemplateResponse(
        request,
        "detail.html",
        {"recipe": recipe, "variants": variants, "parent": parent},
    )


@router.get("/recipes/{recipe_id}/edit", response_class=HTMLResponse)
def edit_form(request: Request, session: SessionDep, recipe_id: uuid.UUID) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "edit.html", {"recipe": _get_recipe(session, recipe_id)}
    )


@router.post("/recipes/{recipe_id}/edit")
def edit_submit(
    session: SessionDep,
    recipe_id: uuid.UUID,
    title: Annotated[str, Form()],
    category: Annotated[str, Form()],
    hands_on_min: Annotated[int, Form()],
    total_min: Annotated[int, Form()],
    status: Annotated[str, Form()],
    # Every optional text field defaults to empty. Clearing a description or a
    # note is a legal edit, and an empty form value arrives as "" rather than
    # as a present-but-blank required field.
    description: Annotated[str, Form()] = "",
    servings: Annotated[str, Form()] = "",
    notes_md: Annotated[str, Form()] = "",
    variant_note: Annotated[str, Form()] = "",
    # An unchecked checkbox sends nothing at all, so the default is what
    # actually clears the flag.
    plan_ahead: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    """The plain form covers metadata and notes only.

    Ingredients and steps are changed by describing the change in words and
    reviewing the diff. Letting them be hand-edited here would create a second
    write path that bypasses the gate and leaves no revision history.
    """
    recipe = _get_recipe(session, recipe_id)

    recipe.title = title.strip()
    recipe.category = category.strip()
    recipe.description = description.strip()
    recipe.servings = servings.strip()
    recipe.hands_on_min = hands_on_min
    recipe.total_min = total_min
    recipe.status = status
    recipe.notes_md = notes_md.strip()
    recipe.plan_ahead = plan_ahead
    if recipe.parent_id is not None:
        recipe.variant_note = variant_note.strip() or None

    return RedirectResponse(url=f"/recipes/{recipe.id}", status_code=303)
