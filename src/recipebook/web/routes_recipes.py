"""Index, detail, and the plain edit form."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from recipebook.db import session_scope
from recipebook.domain.bodytext import (
    BodyTextError,
    equipment_from_text,
    equipment_to_text,
    ingredients_from_text,
    ingredients_to_text,
    steps_from_text,
    steps_to_text,
)
from recipebook.mapping import doc_from_recipe
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


def _form_from_recipe(recipe: Recipe) -> dict[str, Any]:
    """The edit form's fields as the recipe currently stands."""
    doc = doc_from_recipe(recipe)
    return {
        "title": doc.title,
        "category": doc.category,
        "description": doc.description,
        "servings": doc.servings,
        "hands_on_min": doc.hands_on_min,
        "total_min": doc.total_min,
        "status": doc.status,
        "plan_ahead": doc.plan_ahead,
        "notes_md": doc.notes_md,
        "variant_note": recipe.variant_note or "",
        "equipment": equipment_to_text(doc.equipment),
        "ingredients": ingredients_to_text(doc.ingredients),
        "steps": steps_to_text(doc.steps),
    }


@router.get("/recipes/{recipe_id}/edit", response_class=HTMLResponse)
def edit_form(request: Request, session: SessionDep, recipe_id: uuid.UUID) -> HTMLResponse:
    recipe = _get_recipe(session, recipe_id)
    return templates.TemplateResponse(
        request, "edit.html", {"recipe": recipe, "form": _form_from_recipe(recipe)}
    )


@router.post("/recipes/{recipe_id}/edit")
def edit_submit(
    request: Request,
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
    equipment: Annotated[str, Form()] = "",
    ingredients: Annotated[str, Form()] = "",
    steps: Annotated[str, Form()] = "",
    # An unchecked checkbox sends nothing at all, so the default is what
    # actually clears the flag.
    plan_ahead: Annotated[bool, Form()] = False,
) -> Response:
    """Direct edits: everything a recipe holds, typed by hand.

    This is the small-change path. Describing a change in words and reviewing
    the diff is the other one, and it is what earns its keep when a change has
    knock-on effects across the ingredients, a step, and the notes at once.
    """
    recipe = _get_recipe(session, recipe_id)

    # Parsed before anything is written, so a malformed ingredient line cannot
    # leave the recipe half-updated.
    try:
        parsed_equipment = equipment_from_text(equipment)
        parsed_ingredients = ingredients_from_text(ingredients)
        parsed_steps = steps_from_text(steps)
    except BodyTextError as exc:
        submitted = _form_from_recipe(recipe) | {
            "title": title,
            "category": category,
            "description": description,
            "servings": servings,
            "hands_on_min": hands_on_min,
            "total_min": total_min,
            "status": status,
            "plan_ahead": plan_ahead,
            "notes_md": notes_md,
            "variant_note": variant_note,
            "equipment": equipment,
            "ingredients": ingredients,
            "steps": steps,
        }
        return templates.TemplateResponse(
            request,
            "edit.html",
            {"recipe": recipe, "form": submitted, "error": str(exc)},
            status_code=400,
        )

    recipe.title = title.strip()
    recipe.category = category.strip()
    recipe.description = description.strip()
    recipe.servings = servings.strip()
    recipe.hands_on_min = hands_on_min
    recipe.total_min = total_min
    recipe.status = status
    recipe.notes_md = notes_md.strip()
    recipe.plan_ahead = plan_ahead
    recipe.equipment = [item.model_dump(mode="json") for item in parsed_equipment]
    recipe.ingredients = [item.model_dump(mode="json") for item in parsed_ingredients]
    recipe.steps = [step.model_dump(mode="json") for step in parsed_steps]
    if recipe.parent_id is not None:
        recipe.variant_note = variant_note.strip() or None

    return RedirectResponse(url=f"/recipes/{recipe.id}", status_code=303)
