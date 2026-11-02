"""Waiting on a slow call, and finding it again afterwards.

The form posts that start an import or a revision redirect here. While the
call runs this is a waiting page; once it is done the same URL redirects to the
result; if it failed, it is the form again, with what was typed and why it
did not work. So the URL is safe to reload, to leave, and to come back to.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from recipebook.db import session_scope
from recipebook.domain.jobs import close, result_url
from recipebook.domain.trash import visible
from recipebook.models import Job
from recipebook.web.responses import see_other
from recipebook.web.templating import build_templates

router = APIRouter()
templates = build_templates()

SessionDep = Annotated[Session, Depends(session_scope)]


def get_job(session: Session, job_id: uuid.UUID) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job")
    return job


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, session: SessionDep, job_id: uuid.UUID) -> Response:
    job = get_job(session, job_id)
    recipe = visible(session, job.recipe_id) if job.recipe_id else None

    url = result_url(job)
    if url is not None:
        return RedirectResponse(url=url, status_code=303)

    if job.status == "failed":
        # The form again, filled in. `retry_of` lets the next attempt close
        # this one, so a failure that was retried stops being listed.
        if job.kind == "import":
            return templates.TemplateResponse(
                request, "import.html", {"raw": job.input, "error": job.error, "retry_of": job.id}
            )
        if recipe is not None:
            return templates.TemplateResponse(
                request,
                "revise.html",
                {
                    "recipe": recipe,
                    "instruction": job.input,
                    "error": job.error,
                    "retry_of": job.id,
                },
            )
        raise HTTPException(status_code=404, detail="The recipe this was revising is gone.")

    return templates.TemplateResponse(request, "job.html", {"job": job, "recipe": recipe})


@router.get("/jobs/{job_id}/status")
def job_status(session: SessionDep, job_id: uuid.UUID) -> JSONResponse:
    """What the waiting page polls. Anything but running means: go to `url`."""
    job = get_job(session, job_id)
    return JSONResponse(
        {"status": job.status, "url": result_url(job) or f"/jobs/{job.id}"},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/jobs/{job_id}/dismiss")
def job_dismiss(session: SessionDep, job_id: uuid.UUID) -> Response:
    close(get_job(session, job_id))
    return see_other(session, "/")


def close_retried(session: Session, retry_of: str) -> None:
    """Close the failed job a new attempt replaces. A bad id is ignored."""
    try:
        job = session.get(Job, uuid.UUID(retry_of))
    except ValueError:
        return
    if job is not None and job.status == "failed":
        close(job)
