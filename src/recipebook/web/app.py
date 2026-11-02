"""FastAPI application.

Binds to loopback. `tailscale serve --bg 8000` puts it on the tailnet with TLS,
so nothing here knows about certificates or hostnames.
"""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import ProgrammingError
from starlette.exceptions import HTTPException as StarletteHTTPException

from recipebook.db import session_context
from recipebook.domain.jobs import interrupt_running
from recipebook.web.routes_import import router as import_router
from recipebook.web.routes_jobs import router as jobs_router
from recipebook.web.routes_recipes import router as recipes_router
from recipebook.web.routes_revise import router as revise_router
from recipebook.web.routes_trash import router as trash_router
from recipebook.web.templating import STATIC_DIR, build_templates

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Fail the jobs the last process was running when it stopped.

    Their calls ran on threads that died with it. Left alone, each would be a
    waiting page that never stops waiting; failed, it hands back what was typed
    so it can be sent again.

    A missing jobs table is logged, not raised. A deploy rebuilds the container
    and *then* migrates, through `docker compose exec` — and exec needs a
    running container. Failing startup here would put the app in a restart
    loop that the migration meant to fix it can never reach.
    """
    try:
        with session_context() as session:
            interrupted = interrupt_running(session)
    except ProgrammingError:
        log.warning("no jobs table yet; run `alembic upgrade head`")
        interrupted = 0
    if interrupted:
        log.warning("marked %d interrupted job(s) as failed", interrupted)
    yield


app = FastAPI(title="recipe-book", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(import_router)
app.include_router(jobs_router)
app.include_router(revise_router)
app.include_router(trash_router)
app.include_router(recipes_router)

templates = build_templates()


@app.middleware("http")
async def no_stale_pages(request: Request, call_next: Callable[..., Any]) -> Response:
    """Never let a browser reuse a page.

    Every HTML page here is a live view of a row that the next request may
    change. Without a header, browsers apply heuristic caching, and following a
    redirect straight after a write is exactly when they serve the old copy —
    the page looks unchanged until you refresh.

    Static assets are the exception, and templates ask for them through
    `static_url`, which puts a hash of the file's contents in the query string.
    That is what makes caching them safe: the URL changes when the bytes do, so
    a fingerprinted response can be kept for a year and a deploy still reaches
    the browser immediately.

    A /static/ request with no fingerprint gets no header at all, which leaves
    the browser's own heuristics in charge — right for a URL typed by hand or
    held in an old page, and never wrong for long.
    """
    response: Response = await call_next(request)
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    elif request.query_params.get("v"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )
