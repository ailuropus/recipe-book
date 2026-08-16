"""Jinja environment and the filters templates rely on."""

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


def build_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    filters: dict[str, Any] = {
        "markdown": markdown,
        "markdown_inline": markdown_inline,
        "minutes": minutes,
    }
    templates.env.filters.update(filters)
    templates.env.trim_blocks = True
    templates.env.lstrip_blocks = True
    return templates
