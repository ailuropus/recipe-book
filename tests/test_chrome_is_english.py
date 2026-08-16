"""The interface is English; recipe content is Russian.

The brief rules out an i18n framework for a single locale, so the separation is
kept by a rule plus this test rather than by machinery. The rule: user-visible
strings the *application* produces are English, and Russian only ever arrives
from the database, the cook, or the model.

Code comments are exempt — a comment quoting a Russian example is explaining
behaviour, not rendering an interface.
"""

import re
from pathlib import Path

import pytest

CYRILLIC = re.compile(r"[Ѐ-ӿ]")

SRC = Path(__file__).resolve().parent.parent / "src" / "recipebook"

# Files that emit user-visible text and must therefore stay ASCII.
CHROME_GLOBS = ("templates/**/*.html", "domain/render.py", "web/**/*.py")


def _chrome_files() -> list[Path]:
    found: list[Path] = []
    for glob in CHROME_GLOBS:
        found.extend(p for p in SRC.glob(glob) if p.is_file())
    return sorted(found)


def _strip_comments(source: str, path: Path) -> str:
    if path.suffix == ".py":
        return "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    return source


def test_there_is_chrome_to_check() -> None:
    """Guard against this suite silently passing because the globs stopped
    matching anything."""
    assert _chrome_files(), f"no chrome files matched under {SRC}"


@pytest.mark.parametrize("path", _chrome_files(), ids=lambda p: str(p.name))
def test_chrome_contains_no_cyrillic(path: Path) -> None:
    body = _strip_comments(path.read_text(encoding="utf-8"), path)
    found = CYRILLIC.findall(body)
    assert not found, (
        f"{path} contains Cyrillic ({''.join(sorted(set(found)))!r}). "
        "Interface chrome is English; Russian belongs in the database."
    )
