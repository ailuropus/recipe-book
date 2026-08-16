"""Index, detail, and the plain edit form."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from recipebook.db import session_scope
from recipebook.mapping import apply_doc, doc_from_recipe
from recipebook.models import Recipe
from recipebook.web.forms import FormError, RecipeForm
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
    recipe = _get_recipe(session, recipe_id)
    form = RecipeForm.from_doc(doc_from_recipe(recipe), variant_note=recipe.variant_note or "")
    return templates.TemplateResponse(request, "edit.html", {"recipe": recipe, "form": form})


@router.post("/recipes/{recipe_id}/edit")
def edit_submit(
    request: Request,
    session: SessionDep,
    recipe_id: uuid.UUID,
    form: Annotated[RecipeForm, Form()],
) -> Response:
    """Direct edits: everything a recipe holds, typed by hand.

    This is the small-change path. Describing a change in words and reviewing
    the diff is the other one, and it is what earns its keep when a change has
    knock-on effects across the ingredients, a step, and the notes at once.
    """
    recipe = _get_recipe(session, recipe_id)

    # Parsed in full before anything is assigned, so a malformed ingredient
    # line cannot leave the recipe half-updated.
    try:
        doc = form.to_doc()
    except FormError as exc:
        return templates.TemplateResponse(
            request,
            "edit.html",
            {"recipe": recipe, "form": form, "error": str(exc)},
            status_code=400,
        )

    apply_doc(recipe, doc)
    if recipe.parent_id is not None:
        recipe.variant_note = form.variant_note.strip() or None

    return RedirectResponse(url=f"/recipes/{recipe.id}", status_code=303)
