"""The review gate.

Propose, look, decide. The proposal is stored the moment it arrives and the
browser is redirected to it, so reloading the review page rereads a row instead
of paying for the same call twice. Nothing reaches the recipe until a decision
is posted.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from recipebook.db import session_scope
from recipebook.domain.diff import count_changed_lines, diff_body, diff_metadata, has_changes
from recipebook.llm.client import LlmCallFailed
from recipebook.llm.reviser import propose_revision
from recipebook.mapping import apply_doc
from recipebook.models import Recipe, Revision
from recipebook.schemas import RecipeDoc
from recipebook.web.templating import build_templates

router = APIRouter()
templates = build_templates()

SessionDep = Annotated[Session, Depends(session_scope)]


def _get_recipe(session: Session, recipe_id: uuid.UUID) -> Recipe:
    recipe = session.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="No such recipe")
    return recipe


def _get_revision(session: Session, revision_id: uuid.UUID) -> Revision:
    revision = session.get(Revision, revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="No such revision")
    return revision


@router.get("/recipes/{recipe_id}/revise", response_class=HTMLResponse)
def revise_form(request: Request, session: SessionDep, recipe_id: uuid.UUID) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "revise.html", {"recipe": _get_recipe(session, recipe_id)}
    )


@router.post("/recipes/{recipe_id}/revise")
def revise_submit(
    request: Request,
    session: SessionDep,
    recipe_id: uuid.UUID,
    instruction: Annotated[str, Form()] = "",
) -> Response:
    recipe = _get_recipe(session, recipe_id)

    try:
        result = propose_revision(session, recipe, instruction)
    except (ValueError, LlmCallFailed, RuntimeError) as exc:
        return templates.TemplateResponse(
            request,
            "revise.html",
            {"recipe": recipe, "instruction": instruction, "error": str(exc)},
            status_code=400,
        )

    # Redirect rather than render: a reload on the review page must not spend
    # money again.
    return RedirectResponse(url=f"/revisions/{result.revision_id}", status_code=303)


@router.get("/revisions/{revision_id}", response_class=HTMLResponse)
def revision_preview(request: Request, session: SessionDep, revision_id: uuid.UUID) -> HTMLResponse:
    """Everything needed to decide, and no way to decide by accident."""
    revision = _get_revision(session, revision_id)
    recipe = _get_recipe(session, revision.recipe_id)

    before = RecipeDoc.model_validate(revision.before_snapshot)
    after = RecipeDoc.model_validate(revision.after_snapshot)
    segments = diff_body(before, after)
    added, removed = count_changed_lines(segments)

    return templates.TemplateResponse(
        request,
        "revision.html",
        {
            "recipe": recipe,
            "revision": revision,
            "meta_changes": diff_metadata(before, after),
            "segments": segments,
            "added": added,
            "removed": removed,
            "unchanged": not has_changes(before, after),
        },
    )


@router.post("/revisions/{revision_id}/apply")
def revision_apply(
    session: SessionDep,
    revision_id: uuid.UUID,
    action: Annotated[str, Form()],
) -> Response:
    revision = _get_revision(session, revision_id)
    recipe = _get_recipe(session, revision.recipe_id)

    if revision.status != "pending":
        # Already decided — most likely a back button and a second submit.
        raise HTTPException(status_code=409, detail="This revision has already been decided.")

    if action == "discard":
        revision.status = "discarded"
        return RedirectResponse(url=f"/recipes/{recipe.id}", status_code=303)

    if action != "replace":
        raise HTTPException(status_code=400, detail=f"Unknown action {action!r}")

    apply_doc(recipe, RecipeDoc.model_validate(revision.after_snapshot))
    revision.status = "applied"
    revision.applied_as = "replace"
    revision.result_recipe_id = recipe.id
    revision.applied_at = datetime.now(UTC)

    return RedirectResponse(url=f"/recipes/{recipe.id}", status_code=303)
