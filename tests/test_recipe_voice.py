"""Recipe content addresses the cook informally, на ты.

The rule is a content rule, so the real enforcement is the prompt that writes
recipes. This guards the fixtures, which are the examples everything else is
read against — a polite-form step slipping in here would quietly become the
house style.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

CONTENT_FILES = [
    ROOT / "src" / "recipebook" / "demo.py",
    ROOT / "tests" / "fixtures.py",
]

# Second-person-plural imperatives: -йте and -ьте are unambiguous, -ите is
# shared with a handful of ordinary nouns in the prepositional case.
POLITE_IMPERATIVE = re.compile(r"\b[А-Яа-яЁё]{3,}(?:йте|ьте|ите)\b")

# Genuine words that end like an imperative but are not one. Extend when a real
# one trips the check rather than loosening the pattern.
NOT_IMPERATIVES = {"сите"}

POLITE_PRONOUN = re.compile(r"\b(?:[Вв]ы|[Вв]ам|[Вв]ас|[Вв]ами|[Вв]аш\w*)\b")


@pytest.mark.parametrize("path", CONTENT_FILES, ids=lambda p: p.name)
def test_no_polite_imperatives(path: Path) -> None:
    found = [
        f"{path.name}:{lineno} {match.group()}"
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        for match in POLITE_IMPERATIVE.finditer(line)
        if match.group().lower() not in NOT_IMPERATIVES
    ]
    assert not found, "Recipe content is на ты. Use the ты imperative: " + "; ".join(found)


@pytest.mark.parametrize("path", CONTENT_FILES, ids=lambda p: p.name)
def test_no_polite_pronouns(path: Path) -> None:
    found = [
        f"{path.name}:{lineno} {match.group()}"
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        for match in POLITE_PRONOUN.finditer(line)
    ]
    assert not found, "Recipe content is на ты: " + "; ".join(found)


def test_the_checked_files_exist_and_hold_russian() -> None:
    """Guards the guard: a renamed fixture file must not silently pass."""
    for path in CONTENT_FILES:
        assert path.exists(), path
        assert re.search(r"[А-Яа-яЁё]", path.read_text(encoding="utf-8")), path
