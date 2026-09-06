"""Index, detail, and the plain edit form."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from recipebook.db import session_scope
from recipebook.domain.history import history_for, latest_undoable, record_manual_edit
from recipebook.domain.trash import IN_BANK, visible, visible_parent_ids
from recipebook.llm.asker import ask_about
from recipebook.llm.client import LlmCallFailed
from recipebook.mapping import apply_doc, doc_from_recipe
from recipebook.models import Recipe
from recipebook.web.forms import FormError, RecipeForm
from recipebook.web.responses import see_other
from recipebook.web.templating import build_templates

router = APIRouter()
templates = build_templates()

SessionDep = Annotated[Session, Depends(session_scope)]


def _get_recipe(session: Session, recipe_id: uuid.UUID) -> Recipe:
    recipe = visible(session, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="No such recipe")
    return recipe


def _require_in_bank(recipe: Recipe) -> Recipe:
    """Refuse to change a recipe that is sitting in the trash.

    409 rather than 404: the page is right there and says what to do about it,
    so a stale tab explains itself instead of claiming the recipe is gone.
    """
    if recipe.in_trash:
        raise HTTPException(
            status_code=409,
            detail="That recipe is in the trash. Restore it before changing it.",
        )
    return recipe


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    session: SessionDep,
    q: Annotated[str, Query()] = "",
    category: Annotated[str, Query()] = "",
    status: Annotated[str, Query()] = "",
    deleted: Annotated[str, Query()] = "",
) -> HTMLResponse:
    statement = select(Recipe).where(IN_BANK)

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

    categories = list(
        session.scalars(select(Recipe.category).where(IN_BANK).distinct().order_by(Recipe.category))
    )

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "recipes": recipes,
            "categories": categories,
            "q": q,
            "active_category": category,
            "active_status": status,
            "visible_parents": visible_parent_ids(session, recipes),
            "deleted_recipe": _just_deleted(session, deleted),
        },
    )


def _just_deleted(session: Session, deleted: str) -> Recipe | None:
    """The recipe the confirmation shield is about, if there is one.

    Read back from the database rather than trusted from the URL, so the shield
    can only ever offer to restore something that really is in the trash. A
    stale or hand-typed `?deleted=` shows no shield rather than an error — this
    is the index, and it has a job to do either way.
    """
    if not deleted.strip():
        return None
    try:
        recipe_id = uuid.UUID(deleted.strip())
    except ValueError:
        return None
    recipe = session.get(Recipe, recipe_id)
    return recipe if recipe is not None and recipe.in_trash else None


@router.get("/recipes/{recipe_id}", response_class=HTMLResponse)
def detail(request: Request, session: SessionDep, recipe_id: uuid.UUID) -> HTMLResponse:
    recipe = _get_recipe(session, recipe_id)
    return templates.TemplateResponse(request, "detail.html", _detail_context(session, recipe))


def _detail_context(session: Session, recipe: Recipe) -> dict[str, Any]:
    """Everything the detail page needs, so the ask route can re-render it."""
    # Variants in the trash are not listed: the trash bin is the one screen
    # that shows deleted recipes. The parent is shown even when it is in the
    # trash — marked as deleted — because "variant of" is what this recipe is,
    # and dropping the line would leave the variant note explaining nothing. A
    # purged parent is the exception: the link stays in the database and stops
    # being drawn.
    return {
        "recipe": recipe,
        "variants": list(
            session.scalars(
                select(Recipe).where(Recipe.parent_id == recipe.id, IN_BANK).order_by(Recipe.title)
            )
        ),
        "parent": visible(session, recipe.parent_id) if recipe.parent_id else None,
        "history": history_for(session, recipe.id),
        "undoable": latest_undoable(session, recipe.id),
    }


@router.post("/recipes/{recipe_id}/ask", response_class=HTMLResponse)
def ask_submit(
    request: Request,
    session: SessionDep,
    recipe_id: uuid.UUID,
    question: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Answer a question about this recipe, in place.

    Nothing is stored but the cost row. The answer is for the person standing
    at the stove right now; if it turns out to be worth keeping, it belongs in
    the recipe's notes, which is an edit.
    """
    recipe = _require_in_bank(_get_recipe(session, recipe_id))
    context = _detail_context(session, recipe)

    try:
        result = ask_about(session, recipe, question)
    except (ValueError, LlmCallFailed, RuntimeError) as exc:
        return templates.TemplateResponse(
            request,
            "detail.html",
            context | {"question": question, "ask_error": str(exc)},
            status_code=400,
        )

    return templates.TemplateResponse(
        request,
        "detail.html",
        context
        | {
            "question": result.question,
            "answer": result.answer,
            "ask_cost": result.cost_usd,
        },
    )


@router.get("/recipes/{recipe_id}/edit", response_class=HTMLResponse)
def edit_form(request: Request, session: SessionDep, recipe_id: uuid.UUID) -> HTMLResponse:
    recipe = _require_in_bank(_get_recipe(session, recipe_id))
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
    recipe = _require_in_bank(_get_recipe(session, recipe_id))

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

    # Snapshot before writing, so the hand edit lands in the history with a
    # complete before/after pair and undo treats it like any other change.
    before = doc_from_recipe(recipe)
    apply_doc(recipe, doc)
    if recipe.parent_id is not None:
        recipe.variant_note = form.variant_note.strip() or None
    record_manual_edit(session, recipe, before, doc)

    return see_other(session, f"/recipes/{recipe.id}")
