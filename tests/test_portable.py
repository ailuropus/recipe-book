"""JSON export and import.

This is the file that outlives the app, so the property under test is that a
bank survives a round trip through it with its lineage intact.
"""

import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from recipebook.demo import demo_recipes, demo_variant_of_pizza
from recipebook.mapping import doc_from_recipe, recipe_from_doc
from recipebook.models import Recipe
from recipebook.portable import (
    FORMAT_VERSION,
    export_all,
    export_json,
    import_export,
    parse_export,
)
from tests.fixtures import pizza


@pytest.fixture
def bank(session: Session) -> list[Recipe]:
    """Three recipes and a variant of the first."""
    docs = demo_recipes()
    parent = recipe_from_doc(docs[0])
    session.add(parent)
    for doc in docs[1:]:
        session.add(recipe_from_doc(doc))
    session.flush()

    variant = recipe_from_doc(demo_variant_of_pizza())
    variant.parent_id = parent.id
    variant.variant_note = "Полбяная мука."
    session.add(variant)
    session.flush()
    return list(session.scalars(select(Recipe)))


def test_export_carries_every_recipe(session: Session, bank: list[Recipe]) -> None:
    export = export_all(session)
    assert export.format_version == FORMAT_VERSION
    assert len(export.recipes) == len(bank)


def test_export_carries_identity_and_lineage(session: Session, bank: list[Recipe]) -> None:
    """A RecipeDoc deliberately has no id. The portable form must."""
    export = export_all(session)
    variant = next(r for r in export.recipes if r.parent_id is not None)

    assert variant.id is not None
    assert variant.variant_note == "Полбяная мука."
    parent = next(r for r in export.recipes if r.id == variant.parent_id)
    assert parent.title == "Пицца на тонком тесте"


def test_parents_come_before_their_children(session: Session, bank: list[Recipe]) -> None:
    export = export_all(session)
    positions = {recipe.id: i for i, recipe in enumerate(export.recipes)}
    for recipe in export.recipes:
        if recipe.parent_id is not None:
            assert positions[recipe.parent_id] < positions[recipe.id]


def test_export_is_valid_json_with_a_stable_shape(session: Session, bank: list[Recipe]) -> None:
    payload = json.loads(export_json(session))
    assert set(payload) == {"format_version", "exported_at", "recipes"}
    assert payload["recipes"][0]["ingredients"][0]["name"]


def test_round_trip_into_an_empty_database_restores_everything(
    session: Session, bank: list[Recipe]
) -> None:
    payload = export_json(session)
    before = {r.id: doc_from_recipe(r) for r in bank}
    lineage = {r.id: (r.parent_id, r.variant_note) for r in bank}

    session.query(Recipe).delete()
    session.flush()

    report = import_export(session, parse_export(payload))
    assert report.added == len(before)

    restored = list(session.scalars(select(Recipe)))
    assert {r.id: doc_from_recipe(r) for r in restored} == before
    assert {r.id: (r.parent_id, r.variant_note) for r in restored} == lineage


def test_importing_the_same_file_twice_changes_nothing(
    session: Session, bank: list[Recipe]
) -> None:
    """Merging by id, so a re-run is a no-op rather than a duplicate bank."""
    payload = export_json(session)

    report = import_export(session, parse_export(payload))
    assert report.added == 0
    assert report.updated == 0
    assert report.skipped == len(bank)
    assert session.query(Recipe).count() == len(bank)


def test_import_updates_a_changed_recipe_in_place(session: Session, bank: list[Recipe]) -> None:
    payload = parse_export(export_json(session))
    target = payload.recipes[0]
    target.title = "Переименованная пицца"
    target.notes_md = "Заметка из файла."

    report = import_export(session, payload)
    assert report.updated == 1

    recipe = session.get(Recipe, target.id)
    assert recipe is not None
    assert recipe.title == "Переименованная пицца"
    assert recipe.notes_md == "Заметка из файла."


def test_merge_leaves_recipes_the_file_does_not_mention(
    session: Session, bank: list[Recipe]
) -> None:
    """A restore must never quietly delete what it does not know about."""
    payload = parse_export(export_json(session))
    payload.recipes = payload.recipes[:1]

    import_export(session, payload, mode="merge")
    assert session.query(Recipe).count() == len(bank)


def test_replace_deletes_what_the_file_does_not_mention(
    session: Session, bank: list[Recipe]
) -> None:
    payload = parse_export(export_json(session))
    kept = payload.recipes[0]
    payload.recipes = [kept]

    import_export(session, payload, mode="replace")
    remaining = list(session.scalars(select(Recipe)))
    assert [r.id for r in remaining] == [kept.id]


def test_a_child_listed_before_its_parent_still_loads(session: Session) -> None:
    """Hand-edited files do not have to be in dependency order."""
    parent = recipe_from_doc(pizza())
    session.add(parent)
    session.flush()
    child = recipe_from_doc(pizza())
    child.title = "Вариант"
    child.parent_id = parent.id
    session.add(child)
    session.flush()

    payload = parse_export(export_json(session))
    payload.recipes.reverse()
    parent_id = parent.id

    session.query(Recipe).delete()
    session.flush()

    import_export(session, payload)
    restored_child = session.scalars(select(Recipe).where(Recipe.title == "Вариант")).one()
    assert restored_child.parent_id == parent_id


def test_a_parent_that_is_nowhere_becomes_an_orphan_rather_than_a_failure(
    session: Session,
) -> None:
    """An orphaned variant is recoverable. A refused restore is not."""
    recipe = recipe_from_doc(pizza())
    session.add(recipe)
    session.flush()

    payload = parse_export(export_json(session))
    payload.recipes[0].parent_id = uuid.uuid4()
    session.query(Recipe).delete()
    session.flush()

    import_export(session, payload)
    restored = session.scalars(select(Recipe)).one()
    assert restored.parent_id is None


def test_a_newer_format_version_is_refused_with_an_explanation() -> None:
    payload = json.dumps(
        {"format_version": FORMAT_VERSION + 1, "exported_at": "2026-08-16T00:00:00Z", "recipes": []}
    )
    with pytest.raises(ValueError, match="understands up to"):
        parse_export(payload)


def test_an_export_holds_no_revisions_or_costs(session: Session, bank: list[Recipe]) -> None:
    """History is how a recipe got here, not the recipe."""
    payload = json.loads(export_json(session))
    assert "revisions" not in payload
    assert "llm_calls" not in payload
    assert all("cost_usd" not in recipe for recipe in payload["recipes"])
