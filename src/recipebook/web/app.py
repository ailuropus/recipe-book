"""FastAPI application.

Binds to loopback. `tailscale serve --bg 8000` puts it on the tailnet with TLS,
so nothing here knows about certificates or hostnames.
"""

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from recipebook.web.routes_import import router as import_router
from recipebook.web.routes_recipes import router as recipes_router
from recipebook.web.routes_revise import router as revise_router
from recipebook.web.templating import STATIC_DIR, build_templates

app = FastAPI(title="recipe-book", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(import_router)
app.include_router(revise_router)
app.include_router(recipes_router)

templates = build_templates()


@app.middleware("http")
async def no_stale_pages(request: Request, call_next: Callable[..., Any]) -> Response:
    """Never let a browser reuse a page.

    Every HTML page here is a live view of a row that the next request may
    change. Without a header, browsers apply heuristic caching, and following a
    redirect straight after a write is exactly when they serve the old copy —
    the page looks unchanged until you refresh.

    Static assets are excluded: those are content that only changes when the
    file does, and they are the one thing worth caching.
    """
    response: Response = await call_next(request)
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )
