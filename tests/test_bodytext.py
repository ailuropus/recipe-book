"""The textarea encodings of the structured body sections."""

import pytest

from recipebook.domain.bodytext import (
    BodyTextError,
    equipment_from_text,
    equipment_to_text,
    ingredients_from_text,
    ingredients_to_text,
    steps_from_text,
    steps_to_text,
)
from recipebook.schemas import Equipment, Ingredient, Step
from tests.fixtures import pizza


def test_ingredients_round_trip() -> None:
    """What the form shows must parse back to what the recipe held."""
    original = pizza().ingredients
    assert ingredients_from_text(ingredients_to_text(original)) == original


def test_equipment_round_trips() -> None:
    original = pizza().equipment
    assert equipment_from_text(equipment_to_text(original)) == original


def test_steps_round_trip_preserves_internal_line_breaks() -> None:
    """Step 2 of the fixture is deliberately two lines.

    Line breaks inside a step are the author's, and losing them here would
    reflow the text and turn a one-word edit into a whole-paragraph diff.
    """
    original = pizza().steps
    assert "\n" in original[1].text_md
    assert steps_from_text(steps_to_text(original)) == original


def test_trailing_empty_fields_are_dropped() -> None:
    text = ingredients_to_text([Ingredient(name="соль", qty="10", unit="г")])
    assert text == "соль | 10 | г"


def test_a_bare_name_is_a_valid_ingredient() -> None:
    assert ingredients_from_text("соль по вкусу") == [Ingredient(name="соль по вкусу")]


def test_empty_middle_field_is_kept() -> None:
    """A quantity with no unit, e.g. '2 зубчика' written as a bare qty."""
    assert ingredients_from_text("чеснок | 2 |  | крупные") == [
        Ingredient(name="чеснок", qty="2", unit=None, note="крупные")
    ]


def test_blank_lines_are_ignored() -> None:
    assert ingredients_from_text("\n\nмука | 500 | г\n\n\nвода | 325 | мл\n") == [
        Ingredient(name="мука", qty="500", unit="г"),
        Ingredient(name="вода", qty="325", unit="мл"),
    ]


def test_steps_are_renumbered_by_position() -> None:
    """Deleting a step must not leave a gap in the numbering."""
    steps = steps_from_text("Первый.\n---\nВторой.\n---\nТретий.")
    assert [s.n for s in steps] == [1, 2, 3]

    without_middle = steps_from_text("Первый.\n---\nТретий.")
    assert [s.n for s in without_middle] == [1, 2]
    assert without_middle[1].text_md == "Третий."


def test_empty_step_blocks_are_dropped() -> None:
    assert steps_from_text("---\n\nПервый.\n---\n\n---\nВторой.\n---\n") == [
        Step(n=1, text_md="Первый."),
        Step(n=2, text_md="Второй."),
    ]


def test_everything_empty_parses_to_empty_lists() -> None:
    assert ingredients_from_text("") == []
    assert equipment_from_text("   \n\n") == []
    assert steps_from_text("") == []


def test_too_many_fields_is_rejected_with_the_line_number() -> None:
    with pytest.raises(BodyTextError) as caught:
        ingredients_from_text("мука | 500 | г\nвода | 325 | мл | холодная | лишнее")
    assert "Line 2" in str(caught.value)


def test_a_missing_name_is_rejected() -> None:
    with pytest.raises(BodyTextError) as caught:
        ingredients_from_text("| 500 | г")
    assert "Line 1" in str(caught.value)


def test_equipment_without_a_name_is_rejected() -> None:
    with pytest.raises(BodyTextError):
        equipment_from_text("| Прогреть 40 минут")


def test_separator_only_matches_on_its_own_line() -> None:
    """A step may legitimately contain a dash run mid-sentence."""
    steps = steps_from_text("Раскатай тесто --- тонко, но не до дыр.")
    assert len(steps) == 1
    assert steps[0].text_md == "Раскатай тесто --- тонко, но не до дыр."


def test_equipment_note_is_optional() -> None:
    assert equipment_from_text("Кухонные весы") == [Equipment(item="Кухонные весы")]
