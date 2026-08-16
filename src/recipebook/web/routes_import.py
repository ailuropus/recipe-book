"""Paste a recipe, review what came back, then save.

The LLM call happens on the way to the review screen. The save is a separate
request over ordinary form fields, so what gets stored is what was on screen —
not what the model said, if the two differ.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from recipebook.db import session_scope
from recipebook.llm.client import LlmCallFailed
from recipebook.llm.importer import import_recipe
from recipebook.mapping import recipe_from_doc
from recipebook.models import LlmCall
from recipebook.web.forms import FormError, ImportSaveForm, RecipeForm
from recipebook.web.responses import see_other
from recipebook.web.templating import build_templates

router = APIRouter()
templates = build_templates()

SessionDep = Annotated[Session, Depends(session_scope)]


@router.get("/import", response_class=HTMLResponse)
def import_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "import.html", {})


@router.post("/import")
def import_submit(
    request: Request,
    session: SessionDep,
    raw: Annotated[str, Form()] = "",
) -> Response:
    try:
        result = import_recipe(session, raw)
    except (ValueError, LlmCallFailed, RuntimeError) as exc:
        # RuntimeError covers a missing API key, which is worth saying plainly
        # rather than turning into a 500.
        return templates.TemplateResponse(
            request,
            "import.html",
            {"raw": raw, "error": str(exc)},
            status_code=400,
        )

    return templates.TemplateResponse(
        request,
        "import_review.html",
        {
            "form": RecipeForm.from_doc(result.doc),
            "llm_call_id": result.llm_call_id,
            "cost_usd": result.cost_usd,
        },
    )


@router.post("/import/save")
def import_save(
    request: Request,
    session: SessionDep,
    form: Annotated[ImportSaveForm, Form()],
) -> Response:
    try:
        doc = form.to_doc()
    except FormError as exc:
        return templates.TemplateResponse(
            request,
            "import_review.html",
            {"form": form, "llm_call_id": form.llm_call_id, "error": str(exc)},
            status_code=400,
        )

    recipe = recipe_from_doc(doc)
    session.add(recipe)
    session.flush()

    # The import call was made before the recipe existed. Attach it now, so the
    # cost of getting this recipe in is counted against this recipe.
    if form.llm_call_id:
        call = session.get(LlmCall, uuid.UUID(form.llm_call_id))
        if call is not None:
            call.recipe_id = recipe.id

    return see_other(session, f"/recipes/{recipe.id}")
