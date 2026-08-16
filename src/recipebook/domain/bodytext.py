"""Plain-text encodings of the structured body sections.

The edit form has to put equipment, ingredients, and steps into a textarea and
read them back with no JavaScript editor involved. Each section gets a small
line format chosen so that parsing what was formatted returns what went in.

The formats are deliberately dumb:

    equipment     one per line   item | note
    ingredients   one per line   name | qty | unit | note
    steps         separated by a line containing only ---

Trailing empty fields are dropped when formatting, so an ingredient with no
note is just `соль | 10 | г`. A value may not itself contain `|`; the parser
says so rather than guessing where the boundary was.
"""

from collections.abc import Sequence

from recipebook.schemas import Equipment, Ingredient, Step

FIELD_SEPARATOR = "|"
STEP_SEPARATOR = "---"


class BodyTextError(ValueError):
    """A line the parser cannot read, worded for the person who typed it."""


def _join_fields(values: Sequence[str]) -> str:
    trimmed = list(values)
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    return f" {FIELD_SEPARATOR} ".join(trimmed)


def _split_fields(line: str, count: int, lineno: int, what: str) -> list[str]:
    parts = [part.strip() for part in line.split(FIELD_SEPARATOR)]
    if len(parts) > count:
        raise BodyTextError(
            f"Line {lineno}: an {what} takes at most {count} fields separated by "
            f"'{FIELD_SEPARATOR}', and this line has {len(parts)}. "
            f"A value cannot contain '{FIELD_SEPARATOR}' itself."
        )
    parts.extend([""] * (count - len(parts)))
    return parts


def equipment_to_text(items: Sequence[Equipment]) -> str:
    return "\n".join(_join_fields([item.item, item.note or ""]) for item in items)


def equipment_from_text(text: str) -> list[Equipment]:
    out: list[Equipment] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        item, note = _split_fields(line, 2, lineno, "equipment entry")
        if not item:
            raise BodyTextError(f"Line {lineno}: equipment needs a name before the first '|'.")
        out.append(Equipment(item=item, note=note or None))
    return out


def ingredients_to_text(items: Sequence[Ingredient]) -> str:
    return "\n".join(
        _join_fields([item.name, item.qty or "", item.unit or "", item.note or ""])
        for item in items
    )


def ingredients_from_text(text: str) -> list[Ingredient]:
    out: list[Ingredient] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        name, qty, unit, note = _split_fields(line, 4, lineno, "ingredient")
        if not name:
            raise BodyTextError(f"Line {lineno}: an ingredient needs a name before the first '|'.")
        out.append(Ingredient(name=name, qty=qty or None, unit=unit or None, note=note or None))
    return out


def steps_to_text(steps: Sequence[Step]) -> str:
    return f"\n{STEP_SEPARATOR}\n".join(step.text_md.strip() for step in steps)


def steps_from_text(text: str) -> list[Step]:
    """Split on separator lines and renumber by position.

    Numbering is never taken from the text. Deleting the second of five steps
    should leave four consecutively numbered steps, not a gap, and asking the
    typist to renumber by hand would be a needless way to introduce errors.
    """
    blocks: list[list[str]] = [[]]
    for raw in text.splitlines():
        if raw.strip() == STEP_SEPARATOR:
            blocks.append([])
        else:
            blocks[-1].append(raw)

    steps: list[Step] = []
    for block in blocks:
        # Only the ends are stripped: line breaks inside a step are the
        # author's and are preserved all the way through to the diff.
        body = "\n".join(block).strip()
        if body:
            steps.append(Step(n=len(steps) + 1, text_md=body))
    return steps
