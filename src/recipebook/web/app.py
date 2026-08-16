"""FastAPI application.

Binds to loopback. `tailscale serve --bg 8000` puts it on the tailnet with TLS,
so nothing here knows about certificates or hostnames.
"""

from fastapi import FastAPI, Request
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


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )
