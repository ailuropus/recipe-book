"""Renderer tests.

Determinism is the load-bearing property. If rendering the same document twice
could differ, every diff would carry phantom changes and the review gate would
be worse than useless — it would train you to skim.
"""

from recipebook.domain.render import render_body, render_full
from recipebook.schemas import Equipment, Ingredient, RecipeDoc, Step
from tests.fixtures import pizza


def test_render_is_deterministic() -> None:
    doc = pizza()
    assert render_full(doc) == render_full(doc)
    assert render_body(doc) == render_body(doc)


def test_render_is_stable_across_equal_documents() -> None:
    """Two documents built independently but equal in content render alike."""
    assert render_full(pizza()) == render_full(pizza())


def test_round_trip_through_json_does_not_change_the_render() -> None:
    """Recipes travel through JSONB and through export files. Neither trip may
    perturb a single byte of the render, or stored diffs would rot."""
    doc = pizza()
    revived = RecipeDoc.model_validate(doc.model_dump())
    assert render_full(revived) == render_full(doc)


def test_body_excludes_metadata() -> None:
    """Metadata is reported by the metadata diff. Including it in the body too
    would report every metadata change twice."""
    body = render_body(pizza())
    assert "Основные блюда" not in body
    assert "plan ahead" not in body
    assert "Пицца на тонком тесте" not in body


def test_full_includes_metadata() -> None:
    full = render_full(pizza())
    assert "# Пицца на тонком тесте" in full
    assert "category:" in full
    assert "plan ahead:   yes" in full


def test_ingredient_lines_are_one_per_ingredient() -> None:
    body = render_body(pizza())
    ingredient_lines = [line for line in body.splitlines() if line.startswith("- ") and "—" in line]
    assert "- мука — 500 г (Caputo 00)" in ingredient_lines
    assert "- вода — 325 мл" in ingredient_lines


def test_ingredient_without_quantity_renders_cleanly() -> None:
    doc = RecipeDoc(
        title="t",
        category="c",
        description="",
        hands_on_min=1,
        total_min=1,
        servings="1",
        plan_ahead=False,
        ingredients=[Ingredient(name="соль", note="по вкусу")],
    )
    assert "- соль (по вкусу)" in render_body(doc)


def test_equipment_note_is_optional() -> None:
    body = render_body(pizza())
    assert "- Камень для пиццы — Прогреть 40 минут" in body
    assert "- Кухонные весы" in body


def test_multiline_step_keeps_the_authors_line_breaks() -> None:
    """Never re-wrap. Re-wrapping turns a one-word edit into a whole-paragraph
    diff."""
    body = render_body(pizza())
    lines = body.splitlines()
    start = lines.index("2. Вымешивай тесто 10 минут. Готовое тесто перестаёт липнуть")
    assert lines[start + 1] == "   к рукам и при растягивании просвечивает, не разрываясь."


def test_empty_sections_are_omitted() -> None:
    doc = RecipeDoc(
        title="t",
        category="c",
        description="",
        hands_on_min=1,
        total_min=1,
        servings="1",
        plan_ahead=False,
        steps=[Step(n=1, text_md="Единственный шаг.")],
    )
    body = render_body(doc)
    assert "## Equipment" not in body
    assert "## Ingredients" not in body
    assert "## Notes" not in body
    assert "## Steps" in body


def test_body_of_an_empty_document_is_empty() -> None:
    doc = RecipeDoc(
        title="t",
        category="c",
        description="",
        hands_on_min=0,
        total_min=0,
        servings="",
        plan_ahead=False,
    )
    assert render_body(doc) == ""


def test_whitespace_in_input_does_not_leak_into_the_render() -> None:
    """Sloppy whitespace from a paste-import must not produce a diff that
    appears to change lines it did not."""
    doc = RecipeDoc(
        title="t",
        category="c",
        description="",
        hands_on_min=1,
        total_min=1,
        servings="1",
        plan_ahead=False,
        equipment=[Equipment(item="  Сковорода  ", note="  чугунная  ")],
        ingredients=[Ingredient(name="  мука  ", qty=" 500 ", unit=" г ")],
        steps=[Step(n=1, text_md="  Обжарьте.  ")],
    )
    body = render_body(doc)
    assert "- Сковорода — чугунная" in body
    assert "- мука — 500 г" in body
    assert "1. Обжарьте." in body


def test_render_ends_with_exactly_one_newline() -> None:
    full = render_full(pizza())
    assert full.endswith("\n")
    assert not full.endswith("\n\n")
