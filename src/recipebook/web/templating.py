"""Jinja environment, the filters templates rely on, and asset URLs."""

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from markupsafe import Markup

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# html=False leaves raw HTML in the source escaped rather than passed through.
# Recipe text arrives from a paste-import and from the model, so it is never
# allowed to inject markup.
_md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})


def markdown(text: str | None) -> Markup:
    if not text:
        return Markup("")
    return Markup(_md.render(text))


def markdown_inline(text: str | None) -> Markup:
    """Markdown without the wrapping <p>, for text inside a list item."""
    if not text:
        return Markup("")
    return Markup(_md.renderInline(text))


def minutes(value: int | None) -> str:
    """Durations read better as h/min once they pass an hour."""
    if value is None:
        return "—"
    if value < 60:
        return f"{value} min"
    hours, rest = divmod(value, 60)
    return f"{hours} h" if rest == 0 else f"{hours} h {rest} min"


# The waiting room's clip, in the formats it might be shipped in. WebM first:
# it is roughly half the size of the mp4, and a browser that cannot play it
# falls straight through to the next <source> without fetching anything. mp4
# second, which is what Safari and iOS take.
@lru_cache(maxsize=64)
def _fingerprint(name: str, mtime_ns: int, size: int) -> str:
    """A short hash of the file's contents.

    Keyed on mtime and size as well as the name so the hash is computed once
    and then recomputed the moment the file is touched — which is what makes
    this work under `uvicorn --reload`, where a stylesheet edit restarts
    nothing.
    """
    return hashlib.sha256((STATIC_DIR / name).read_bytes()).hexdigest()[:10]


def static_url(name: str) -> str:
    """The URL for a static file, carrying a hash of what is in it.

    Without this, a stylesheet is `/static/app.css` before a deploy and
    `/static/app.css` after it. Browsers cache static assets heuristically, so
    the old copy keeps being used against the new HTML — the markup for a new
    feature arrives and none of its rules do, which looks like a broken deploy
    and is a cached file. Changing the URL when the bytes change is what tells
    the browser to go and get it.
    """
    path = STATIC_DIR / name
    try:
        stat = path.stat()
    except OSError:
        # A missing file is the caller's problem, not this function's; hand
        # back the plain URL and let it 404 visibly.
        return f"/static/{name}"
    return f"/static/{name}?v={_fingerprint(name, stat.st_mtime_ns, stat.st_size)}"


BUSY_CLIP_FORMATS = (
    ("running_mausi.webm", "video/webm"),
    ("running_mausi.mp4", "video/mp4"),
)


def busy_clip_sources() -> list[dict[str, str]]:
    """The clip formats actually present on disk, in preference order.

    Checked once at startup rather than per render. With none of them there the
    waiting room falls back to the still mouse, so a missing file is never a
    broken <video> element.
    """
    return [
        {"src": static_url(name), "type": mime}
        for name, mime in BUSY_CLIP_FORMATS
        if (STATIC_DIR / name).exists()
    ]


def build_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    filters: dict[str, Any] = {
        "markdown": markdown,
        "markdown_inline": markdown_inline,
        "minutes": minutes,
    }
    templates.env.filters.update(filters)
    templates.env.globals["static_url"] = static_url
    # Resolved per render rather than pinned at startup, so the clip's own URL
    # picks up a replaced file the same way every other asset does.
    templates.env.globals["busy_clip_sources"] = busy_clip_sources
    templates.env.trim_blocks = True
    templates.env.lstrip_blocks = True
    return templates
