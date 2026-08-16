"""Diffing two recipes for the review gate.

Two diffs, matching the two things the review screen shows:

  diff_metadata — scalar fields, old value against new
  diff_body     — a line-level diff of the rendered body, with long unchanged
                  runs collapsed down to a little context

This is the screen the whole application exists to put in front of you, so it
is worth being fussy about. In particular, long runs of unchanged text have to
collapse: a fifteen-line change buried in a two-hundred-line recipe is
invisible if every unchanged line is on screen, and an invisible change is one
that gets waved through.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal

from recipebook.domain.render import render_body
from recipebook.schemas import RecipeDoc

LineKind = Literal["equal", "insert", "delete"]


@dataclass(frozen=True)
class DiffLine:
    kind: LineKind
    text: str
    # 1-based line numbers, or None where the line does not exist on that side.
    before_no: int | None
    after_no: int | None


@dataclass(frozen=True)
class Gap:
    """A collapsed run of unchanged lines."""

    skipped: int


DiffSegment = DiffLine | Gap


@dataclass(frozen=True)
class MetaChange:
    field: str
    before: str
    after: str


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _minutes(value: int) -> str:
    return f"{value} min"


def _text(value: str) -> str:
    return value.strip()


@dataclass(frozen=True)
class _MetaField:
    attr: str
    # The label shown on the review screen.
    label: str
    format: Callable[[Any], str]


_META_FIELDS: tuple[_MetaField, ...] = (
    _MetaField("title", "title", _text),
    _MetaField("category", "category", _text),
    _MetaField("status", "status", _text),
    _MetaField("servings", "servings", _text),
    _MetaField("hands_on_min", "hands-on", _minutes),
    _MetaField("total_min", "total", _minutes),
    _MetaField("plan_ahead", "plan ahead", _yes_no),
    _MetaField("description", "description", _text),
)


def diff_metadata(before: RecipeDoc, after: RecipeDoc) -> list[MetaChange]:
    """Changed scalar fields only. Unchanged fields are noise on a review screen."""
    changes: list[MetaChange] = []
    for field in _META_FIELDS:
        old = field.format(getattr(before, field.attr))
        new = field.format(getattr(after, field.attr))
        if old != new:
            changes.append(MetaChange(field=field.label, before=old, after=new))
    return changes


def _emit_equal_run(
    lines: Sequence[str],
    before_start: int,
    after_start: int,
    context: int,
    *,
    is_first: bool,
    is_last: bool,
) -> list[DiffSegment]:
    """Render an unchanged run, collapsing the middle when it is long enough.

    A run at the very start of the document only needs its *trailing* context
    (the lines leading into the first change); one at the very end only needs
    its leading context. Anything in between keeps context on both sides.
    """
    total = len(lines)

    head = 0 if is_first else context
    tail = 0 if is_last else context

    if total <= head + tail:
        return [
            DiffLine("equal", line, before_start + i, after_start + i)
            for i, line in enumerate(lines)
        ]

    segments: list[DiffSegment] = [
        DiffLine("equal", line, before_start + i, after_start + i)
        for i, line in enumerate(lines[:head])
    ]
    segments.append(Gap(skipped=total - head - tail))
    if tail:
        offset = total - tail
        segments.extend(
            DiffLine("equal", line, before_start + offset + i, after_start + offset + i)
            for i, line in enumerate(lines[offset:])
        )
    return segments


def diff_lines(before: str, after: str, context: int = 3) -> list[DiffSegment]:
    """Line-level diff of two blocks of text."""
    before_lines = before.splitlines()
    after_lines = after.splitlines()

    # autojunk=False: the heuristic treats lines that recur often as junk, and
    # a recipe is full of repeated short lines. Leaving it on produces diffs
    # that are technically valid and visibly wrong.
    matcher = SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    opcodes = matcher.get_opcodes()

    segments: list[DiffSegment] = []
    for index, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if tag == "equal":
            segments.extend(
                _emit_equal_run(
                    before_lines[i1:i2],
                    before_start=i1 + 1,
                    after_start=j1 + 1,
                    context=context,
                    is_first=index == 0,
                    is_last=index == len(opcodes) - 1,
                )
            )
            continue

        if tag in ("delete", "replace"):
            segments.extend(DiffLine("delete", before_lines[i], i + 1, None) for i in range(i1, i2))
        if tag in ("insert", "replace"):
            segments.extend(DiffLine("insert", after_lines[j], None, j + 1) for j in range(j1, j2))

    return segments


def diff_body(before: RecipeDoc, after: RecipeDoc, context: int = 3) -> list[DiffSegment]:
    """Line-level diff of the rendered recipe body."""
    return diff_lines(render_body(before), render_body(after), context=context)


def has_changes(before: RecipeDoc, after: RecipeDoc) -> bool:
    """Whether anything at all differs.

    A revision that changes nothing should be reported as such rather than
    presented as an empty diff to approve.
    """
    if diff_metadata(before, after):
        return True
    return render_body(before) != render_body(after)


def count_changed_lines(segments: Sequence[DiffSegment]) -> tuple[int, int]:
    """(added, removed) — for the one-line summary above the diff."""
    added = sum(1 for s in segments if isinstance(s, DiffLine) and s.kind == "insert")
    removed = sum(1 for s in segments if isinstance(s, DiffLine) and s.kind == "delete")
    return added, removed
