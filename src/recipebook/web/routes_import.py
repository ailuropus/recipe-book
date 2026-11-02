"""Paste a recipe, review what came back, then save.

The paste is checked, written down as a job, and the browser is sent to wait
on it; the call runs on the server and stores its result on the job. The
review screen reads that stored result, so it can be reloaded, left, and come
back to without paying for the call twice.

The save is a separate request over ordinary form fields, so what gets stored
is what was on screen — not what the model said, if the two differ.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from recipebook.db import session_scope
from recipebook.domain.jobs import close, start_job
from recipebook.llm.importer import check_paste, import_recipe
from recipebook.mapping import doc_to_dict, recipe_from_doc
from recipebook.models import Job, LlmCall
from recipebook.schemas import RecipeDoc
from recipebook.web.background import launch_and_redirect
from recipebook.web.forms import FormError, ImportSaveForm, RecipeForm
from recipebook.web.responses import see_other
from recipebook.web.routes_jobs import close_retried, get_job
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
    retry_of: Annotated[str, Form()] = "",
) -> Response:
    try:
        text = check_paste(raw)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "import.html",
            {"raw": raw, "error": str(exc), "retry_of": retry_of},
            status_code=400,
        )

    if retry_of:
        close_retried(session, retry_of)
    job = start_job(session, kind="import", text=text)
    return launch_and_redirect(session, job, _run_import)


def _run_import(session: Session, job: Job) -> None:
    result = import_recipe(session, job.input)
    job.result_doc = doc_to_dict(result.doc)
    job.llm_call_id = result.llm_call_id


@router.get("/imports/{job_id}", response_class=HTMLResponse)
def import_review(request: Request, session: SessionDep, job_id: uuid.UUID) -> Response:
    job = get_job(session, job_id)
    if job.kind != "import":
        raise HTTPException(status_code=404, detail="No such import")
    if job.recipe_id is not None:
        # Already saved. The review is over; show what it became.
        return RedirectResponse(url=f"/recipes/{job.recipe_id}", status_code=303)
    if job.status != "done" or job.result_doc is None:
        return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)

    call = session.get(LlmCall, job.llm_call_id) if job.llm_call_id else None
    return templates.TemplateResponse(
        request,
        "import_review.html",
        {
            "form": RecipeForm.from_doc(RecipeDoc.model_validate(job.result_doc)),
            "llm_call_id": job.llm_call_id or "",
            "job_id": job.id,
            "cost_usd": f"{call.cost_usd:.4f}" if call is not None else None,
        },
    )


@router.post("/import/save")
def import_save(
    request: Request,
    session: SessionDep,
    form: Annotated[ImportSaveForm, Form()],
) -> Response:
    job = _job_for(session, form.job_id)
    if job is not None and job.recipe_id is not None:
        # Saved once already — a back button and a second press. A duplicate
        # recipe is the wrong answer to that.
        return see_other(session, f"/recipes/{job.recipe_id}")

    try:
        doc = form.to_doc()
    except FormError as exc:
        return templates.TemplateResponse(
            request,
            "import_review.html",
            {
                "form": form,
                "llm_call_id": form.llm_call_id,
                "job_id": form.job_id,
                "error": str(exc),
            },
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

    if job is not None:
        job.recipe_id = recipe.id
        close(job)

    return see_other(session, f"/recipes/{recipe.id}")


def _job_for(session: Session, job_id: str) -> Job | None:
    try:
        return session.get(Job, uuid.UUID(job_id)) if job_id else None
    except ValueError:
        return None
