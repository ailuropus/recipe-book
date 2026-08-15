"""Schema tests.

These cover the three things that would be expensive to discover later: that
the migration and the models agree, that Russian search actually matches across
inflections, and that the variant link cannot lose a recipe.
"""

import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from recipebook.models import Base, LlmCall, Recipe, Revision


def _pizza() -> Recipe:
    return Recipe(
        title="Пицца на тонком тесте",
        category="Основные блюда",
        description="Хрустящая основа, тонкий слой соуса.",
        hands_on_min=40,
        total_min=180,
        servings="2 средние пиццы",
        plan_ahead=True,
        status="tried",
        equipment=[{"item": "Камень для пиццы", "note": "Прогреть заранее"}],
        ingredients=[
            {"name": "мука", "qty": "500", "unit": "г", "note": "Caputo 00"},
            {"name": "яйцо", "qty": "1", "unit": "шт", "note": None},
        ],
        steps=[{"n": 1, "text_md": "Замесите тесто и оставьте подходить на два часа."}],
        notes_md="В прошлый раз тесто было слишком влажным.",
    )


def test_migration_matches_models(engine: Engine) -> None:
    """`alembic upgrade head` must produce exactly what the models declare.

    If this fails, someone edited models.py without writing a migration.
    """
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        diffs = compare_metadata(context, Base.metadata)
    assert diffs == [], f"models and migrations have drifted: {diffs}"


def test_recipe_roundtrip(session: Session) -> None:
    recipe = _pizza()
    session.add(recipe)
    session.flush()

    stored = session.get(Recipe, recipe.id)
    assert stored is not None
    assert stored.ingredients[0]["note"] == "Caputo 00"
    assert stored.steps[0]["n"] == 1
    assert stored.plan_ahead is True


@pytest.mark.parametrize(
    ("query", "why"),
    [
        ("яйца", "plural must match the singular 'яйцо' in the ingredients"),
        ("тесто", "must reach inside the steps JSONB"),
        ("подходит", "verb form must stem to 'подходить' in a step"),
        ("влажный", "must reach the notes"),
        ("Caputo", "Latin brand names must survive the russian config"),
    ],
)
def test_russian_search_matches_across_inflections(session: Session, query: str, why: str) -> None:
    """This is why the config is 'russian' and not 'simple'."""
    session.add(_pizza())
    session.flush()

    matched = session.execute(
        text("SELECT count(*) FROM recipes WHERE search_tsv @@ plainto_tsquery('russian', :q)"),
        {"q": query},
    ).scalar_one()
    assert matched == 1, why


def test_search_does_not_match_unrelated_words(session: Session) -> None:
    session.add(_pizza())
    session.flush()

    matched = session.execute(
        text("SELECT count(*) FROM recipes WHERE search_tsv @@ plainto_tsquery('russian', :q)"),
        {"q": "шоколад"},
    ).scalar_one()
    assert matched == 0


def test_deleting_a_parent_does_not_delete_its_variants(session: Session) -> None:
    """Losing a recipe is the one unrecoverable outcome, so the link breaks
    rather than cascading."""
    parent = _pizza()
    session.add(parent)
    session.flush()

    variant = _pizza()
    variant.title = "Пицца на тонком тесте — с полбой"
    variant.parent_id = parent.id
    variant.variant_note = "Треть муки заменена на полбяную."
    session.add(variant)
    session.flush()

    session.delete(parent)
    session.flush()
    session.expire_all()

    survivor = session.get(Recipe, variant.id)
    assert survivor is not None
    assert survivor.parent_id is None
    assert survivor.variant_note == "Треть муки заменена на полбяную."


def test_recipe_cannot_be_its_own_parent(session: Session) -> None:
    recipe = _pizza()
    session.add(recipe)
    session.flush()

    recipe.parent_id = recipe.id
    with pytest.raises(IntegrityError):
        session.flush()


def test_status_is_constrained(session: Session) -> None:
    recipe = _pizza()
    recipe.status = "delicious"
    session.add(recipe)
    with pytest.raises(IntegrityError):
        session.flush()


def test_revision_defaults_to_pending(session: Session) -> None:
    """A proposal exists in the database before it is applied; that is what the
    review screen reads and what undo later replays."""
    recipe = _pizza()
    session.add(recipe)
    session.flush()

    revision = Revision(
        recipe_id=recipe.id,
        instruction="убавь сахар и добавь корицу",
        before_snapshot={"title": "before"},
        after_snapshot={"title": "after"},
    )
    session.add(revision)
    session.flush()

    assert revision.status == "pending"
    assert revision.applied_at is None
    assert revision.undone_at is None


def test_llm_call_records_cost_and_survives_recipe_deletion(session: Session) -> None:
    """Spend history must outlive the recipe it was spent on."""
    recipe = _pizza()
    session.add(recipe)
    session.flush()

    call = LlmCall(
        recipe_id=recipe.id,
        kind="revise",
        model="claude-opus-5",
        input_tokens=3200,
        output_tokens=2100,
        cost_usd="0.068500",
        latency_ms=9400,
    )
    session.add(call)
    session.flush()

    session.delete(recipe)
    session.flush()
    session.expire_all()

    stored = session.get(LlmCall, call.id)
    assert stored is not None
    assert stored.recipe_id is None
    assert float(stored.cost_usd) == pytest.approx(0.0685)


def test_import_call_may_have_no_recipe(session: Session) -> None:
    """A paste-import is billed before the recipe exists."""
    call = LlmCall(recipe_id=None, kind="import", model="claude-opus-5")
    session.add(call)
    session.flush()
    assert call.id is not None
    assert isinstance(call.id, uuid.UUID)
