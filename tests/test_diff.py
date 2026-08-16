"""Diff tests.

The review screen is the point of the application, so these check the things
that would quietly make it untrustworthy: a change that does not show up, an
unchanged line reported as changed, or a real change buried under so much
unchanged context that it gets waved through.
"""

from collections.abc import Sequence

from recipebook.domain.diff import (
    DiffLine,
    DiffSegment,
    Gap,
    count_changed_lines,
    diff_body,
    diff_lines,
    diff_metadata,
    has_changes,
)
from recipebook.schemas import Ingredient, Step
from tests.fixtures import long_recipe, pizza


def _texts(segments: Sequence[DiffSegment], kind: str) -> list[str]:
    return [s.text for s in segments if isinstance(s, DiffLine) and s.kind == kind]


def test_identical_documents_produce_no_changes() -> None:
    before, after = pizza(), pizza()
    assert diff_metadata(before, after) == []
    assert count_changed_lines(diff_body(before, after)) == (0, 0)
    assert has_changes(before, after) is False


def test_metadata_diff_reports_only_what_changed() -> None:
    before = pizza()
    after = pizza()
    after.total_min = 240
    after.status = "solid"

    changes = {c.field: (c.before, c.after) for c in diff_metadata(before, after)}
    assert changes == {
        "total": ("180 min", "240 min"),
        "status": ("tried", "solid"),
    }


def test_plan_ahead_renders_as_yes_no() -> None:
    before = pizza()
    after = pizza()
    after.plan_ahead = False

    (change,) = diff_metadata(before, after)
    assert change.field == "plan ahead"
    assert (change.before, change.after) == ("yes", "no")


def test_changing_a_quantity_shows_as_one_removal_and_one_insertion() -> None:
    before = pizza()
    after = pizza()
    after.ingredients[3] = Ingredient(name="сахар", qty="10", unit="г")

    segments = diff_body(before, after)
    assert "- сахар — 20 г" in _texts(segments, "delete")
    assert "- сахар — 10 г" in _texts(segments, "insert")
    assert count_changed_lines(segments) == (1, 1)


def test_adding_an_ingredient_is_an_insertion_only() -> None:
    before = pizza()
    after = pizza()
    after.ingredients.append(Ingredient(name="корица", qty="1", unit="ч.л."))

    added, removed = count_changed_lines(diff_body(before, after))
    assert (added, removed) == (1, 0)


def test_a_knock_on_change_shows_in_both_places() -> None:
    """Changing a quantity should surface in the ingredient list *and* in the
    step that mentions it. This is the behaviour the whole revision feature
    depends on, seen from the diff side."""
    before = pizza()
    after = pizza()
    after.ingredients[3] = Ingredient(name="сахар", qty="10", unit="г")
    after.steps[0] = Step(n=1, text_md="Смешайте муку, воду и 10 г сахара.")

    segments = diff_body(before, after)
    inserted = _texts(segments, "insert")
    assert "- сахар — 10 г" in inserted
    assert "1. Смешайте муку, воду и 10 г сахара." in inserted


def test_long_unchanged_runs_collapse() -> None:
    before = long_recipe()
    after = long_recipe()
    after.steps[20] = Step(n=21, text_md="Изменённый шаг.")

    segments = diff_body(before, after, context=3)
    gaps = [s for s in segments if isinstance(s, Gap)]

    assert gaps, "a 40-step recipe with one edit must collapse the unchanged runs"
    assert sum(g.skipped for g in gaps) > 40
    # The change itself, plus a little context, must still be present.
    assert "21. Изменённый шаг." in _texts(segments, "insert")
    assert "21. Шаг номер 21." in _texts(segments, "delete")


def test_collapsed_runs_keep_context_around_the_change() -> None:
    before = long_recipe()
    after = long_recipe()
    after.steps[20] = Step(n=21, text_md="Изменённый шаг.")

    segments = diff_body(before, after, context=3)
    equal_texts = _texts(segments, "equal")

    assert "20. Шаг номер 20." in equal_texts
    assert "22. Шаг номер 22." in equal_texts
    # ...but not the far end of the recipe.
    assert "2. Шаг номер 2." not in equal_texts


def test_no_gap_when_the_document_is_short() -> None:
    segments = diff_lines("a\nb\nc\n", "a\nX\nc\n", context=3)
    assert not [s for s in segments if isinstance(s, Gap)]


def test_line_numbers_track_both_sides() -> None:
    segments = diff_lines("a\nb\nc", "a\nB\nc", context=3)
    lines = [s for s in segments if isinstance(s, DiffLine)]

    deleted = next(s for s in lines if s.kind == "delete")
    assert (deleted.before_no, deleted.after_no) == (2, None)

    inserted = next(s for s in lines if s.kind == "insert")
    assert (inserted.before_no, inserted.after_no) == (None, 2)

    first_equal = next(s for s in lines if s.kind == "equal")
    assert (first_equal.before_no, first_equal.after_no) == (1, 1)


def test_leading_and_trailing_runs_are_trimmed_not_padded() -> None:
    """The start of the document needs no leading context and the end needs no
    trailing context — a unified diff does not show them, and neither do we."""
    before = "\n".join(f"line {i}" for i in range(1, 41))
    after = before.replace("line 20", "line twenty")

    segments = diff_lines(before, after, context=2)
    first, last = segments[0], segments[-1]
    assert isinstance(first, Gap)
    assert isinstance(last, Gap)


def test_has_changes_detects_body_only_changes() -> None:
    before = pizza()
    after = pizza()
    after.notes_md = "Совсем другие заметки."
    assert diff_metadata(before, after) == []
    assert has_changes(before, after) is True


def test_has_changes_detects_metadata_only_changes() -> None:
    before = pizza()
    after = pizza()
    after.category = "Выпечка"
    assert count_changed_lines(diff_body(before, after)) == (0, 0)
    assert has_changes(before, after) is True


def test_reordering_steps_is_visible() -> None:
    before = pizza()
    after = pizza()
    after.steps = [
        Step(n=1, text_md=before.steps[2].text_md),
        Step(n=2, text_md=before.steps[1].text_md),
        Step(n=3, text_md=before.steps[0].text_md),
    ]
    added, removed = count_changed_lines(diff_body(before, after))
    assert added > 0 and removed > 0
