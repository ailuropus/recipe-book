"""Deleting, restoring, and deleting forever.

The property under test throughout is that no row ever leaves the table. That
is what lets a variant of a deleted parent still say where it came from, and it
is the only reason deleting without a confirmation dialog is defensible.
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from recipebook.db import get_engine, get_session_factory
from recipebook.demo import demo_recipes, demo_variant_of_pizza
from recipebook.domain.history import apply_as_variant, undo
from recipebook.domain.trash import TrashRefused, move_to_trash, purge, restore
from recipebook.mapping import doc_to_dict, recipe_from_doc
from recipebook.models import LlmCall, Recipe, Revision
from recipebook.portable import export_all, import_export
from recipebook.schemas import RecipeDoc
from recipebook.web.app import app
from tests.conftest import use_test_database

PIZZA = "Пицца на тонком тесте"
VARIANT = "Пицца на тонком тесте — на полбяной муке"
SOUP = "Луковый суп"


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    """The demo bank: three recipes, and a variant of the first."""
    use_test_database()

    with Session(engine) as setup:
        setup.query(LlmCall).delete()
        setup.query(Revision).delete()
        setup.query(Recipe).delete()
        docs = demo_recipes()
        parent = recipe_from_doc(docs[0])
        setup.add(parent)
        for doc in docs[1:]:
            setup.add(recipe_from_doc(doc))
        setup.flush()
        variant = recipe_from_doc(demo_variant_of_pizza())
        variant.parent_id = parent.id
        variant.variant_note = "Полбяная мука."
        setup.add(variant)
        setup.commit()

    with TestClient(app) as test_client:
        yield test_client

    with Session(engine) as teardown:
        teardown.query(LlmCall).delete()
        teardown.query(Revision).delete()
        teardown.query(Recipe).delete()
        teardown.commit()

    get_engine.cache_clear()
    get_session_factory.cache_clear()


def _id(title: str) -> str:
    with Session(get_engine()) as session:
        return str(session.query(Recipe).filter(Recipe.title == title).one().id)


def _row(recipe_id: str) -> Recipe:
    with Session(get_engine()) as session:
        return session.query(Recipe).filter(Recipe.id == uuid.UUID(recipe_id)).one()


def _delete(client: TestClient, recipe_id: str) -> str:
    response = client.post(f"/recipes/{recipe_id}/delete", follow_redirects=False)
    assert response.status_code == 303
    return str(response.headers["location"])


# --------------------------------------------------------------- deleting


def test_delete_lands_on_the_index_with_the_shield(client: TestClient) -> None:
    """No confirmation before, so the taking-back is on the very next screen."""
    recipe_id = _id(SOUP)
    assert _delete(client, recipe_id) == f"/?deleted={recipe_id}"

    page = client.get("/", params={"deleted": recipe_id}).text
    assert 'class="shield"' in page
    assert SOUP in page
    assert f"/recipes/{recipe_id}/restore" in page


def test_a_deleted_recipe_leaves_the_index_and_the_search(client: TestClient) -> None:
    _delete(client, _id(SOUP))

    assert SOUP not in client.get("/").text
    assert SOUP not in client.get("/", params={"q": "луковый"}).text
    assert SOUP not in client.get("/", params={"category": "Супы"}).text


def test_the_shield_only_appears_for_a_recipe_really_in_the_trash(client: TestClient) -> None:
    """The id comes off the URL, so it is read back rather than believed."""
    page = client.get("/", params={"deleted": _id(SOUP)}).text
    assert 'class="shield"' not in page


def test_a_malformed_shield_id_does_not_break_the_index(client: TestClient) -> None:
    response = client.get("/", params={"deleted": "not-a-uuid"})
    assert response.status_code == 200
    assert 'class="shield"' not in response.text


def test_deleting_is_soft(client: TestClient) -> None:
    recipe_id = _id(SOUP)
    _delete(client, recipe_id)

    row = _row(recipe_id)
    assert row.deleted_at is not None
    assert row.purged_at is None
    assert row.title == SOUP


def test_deleting_a_parent_leaves_its_variants_in_the_bank(client: TestClient) -> None:
    """One press removes one recipe. Never a family."""
    parent_id = _id(PIZZA)
    variant_id = _id(VARIANT)
    _delete(client, parent_id)

    index = client.get("/").text
    # By link, not by title: the variant's title starts with the parent's, so
    # searching the text for one finds the other.
    assert f'"/recipes/{variant_id}"' in index
    assert f'"/recipes/{parent_id}"' not in index


# --------------------------------------------------------------- the bin


def test_the_trash_bin_lists_what_was_deleted(client: TestClient) -> None:
    recipe_id = _id(SOUP)
    _delete(client, recipe_id)

    page = client.get("/trash").text
    assert SOUP in page
    assert f"/recipes/{recipe_id}/restore" in page
    assert f"/recipes/{recipe_id}/purge" in page


def test_an_empty_trash_says_so(client: TestClient) -> None:
    assert "The trash is empty." in client.get("/trash").text


def test_restoring_from_the_bin_returns_to_the_bin(client: TestClient) -> None:
    recipe_id = _id(SOUP)
    _delete(client, recipe_id)

    response = client.post(
        f"/recipes/{recipe_id}/restore", data={"back": "trash"}, follow_redirects=False
    )
    assert response.headers["location"] == "/trash"
    assert SOUP in client.get("/").text


def test_restoring_from_the_shield_returns_to_the_index(client: TestClient) -> None:
    recipe_id = _id(SOUP)
    _delete(client, recipe_id)

    response = client.post(
        f"/recipes/{recipe_id}/restore", data={"back": "index"}, follow_redirects=False
    )
    assert response.headers["location"] == "/"
    assert SOUP in client.get("/").text


def test_an_unknown_return_target_lands_on_the_recipe(client: TestClient) -> None:
    """The set of destinations is fixed here; nothing is taken from the request."""
    recipe_id = _id(SOUP)
    _delete(client, recipe_id)

    response = client.post(
        f"/recipes/{recipe_id}/restore",
        data={"back": "https://example.invalid/"},
        follow_redirects=False,
    )
    assert response.headers["location"] == f"/recipes/{recipe_id}"


def test_restoring_something_that_is_not_deleted_is_refused(client: TestClient) -> None:
    response = client.post(f"/recipes/{_id(SOUP)}/restore", data={"back": "trash"})
    assert response.status_code == 409


# --------------------------------------------------------------- forever


def test_purging_takes_it_out_of_the_bin_and_off_the_web(client: TestClient) -> None:
    recipe_id = _id(SOUP)
    _delete(client, recipe_id)

    response = client.post(f"/recipes/{recipe_id}/purge", follow_redirects=False)
    assert response.headers["location"] == "/trash"

    assert SOUP not in client.get("/trash").text
    assert SOUP not in client.get("/").text
    assert client.get(f"/recipes/{recipe_id}").status_code == 404


def test_purging_keeps_the_row_and_the_variant_link(client: TestClient) -> None:
    """The whole reason a purge is soft: the link stays resolvable."""
    parent_id = _id(PIZZA)
    variant_id = _id(VARIANT)
    _delete(client, parent_id)
    client.post(f"/recipes/{parent_id}/purge", follow_redirects=False)

    parent = _row(parent_id)
    assert parent.purged_at is not None
    assert parent.title == PIZZA

    assert _row(variant_id).parent_id == uuid.UUID(parent_id)


def test_purging_without_going_through_the_trash_is_refused(client: TestClient) -> None:
    response = client.post(f"/recipes/{_id(SOUP)}/purge")
    assert response.status_code == 409


def test_a_purged_recipe_cannot_be_restored(client: TestClient) -> None:
    recipe_id = _id(SOUP)
    _delete(client, recipe_id)
    client.post(f"/recipes/{recipe_id}/purge", follow_redirects=False)

    response = client.post(f"/recipes/{recipe_id}/restore", data={"back": "trash"})
    assert response.status_code == 404


# --------------------------------------------------------------- lineage


def test_a_variant_says_its_parent_is_deleted(client: TestClient) -> None:
    parent_id = _id(PIZZA)
    _delete(client, parent_id)

    page = client.get(f"/recipes/{_id(VARIANT)}").text
    assert "(deleted)" in page
    # Still a link: it is how you reach the page that offers the parent back.
    assert f"/recipes/{parent_id}" in page


def test_a_purged_parent_leaves_no_trace_in_the_interface(client: TestClient) -> None:
    parent_id = _id(PIZZA)
    variant_id = _id(VARIANT)
    _delete(client, parent_id)
    client.post(f"/recipes/{parent_id}/purge", follow_redirects=False)

    page = client.get(f"/recipes/{variant_id}").text
    assert "variant of" not in page
    assert f"/recipes/{parent_id}" not in page

    # And the index stops calling it a variant, for the same reason.
    assert 'class="tag tag--variant"' not in client.get("/").text


def test_a_trashed_variant_is_not_listed_on_its_parent(client: TestClient) -> None:
    parent_id = _id(PIZZA)
    _delete(client, _id(VARIANT))

    page = client.get(f"/recipes/{parent_id}").text
    assert VARIANT not in page


def test_restoring_a_variant_puts_the_lineage_back(client: TestClient) -> None:
    parent_id = _id(PIZZA)
    variant_id = _id(VARIANT)
    _delete(client, variant_id)
    client.post(f"/recipes/{variant_id}/restore", data={"back": "index"}, follow_redirects=False)

    assert VARIANT in client.get(f"/recipes/{parent_id}").text
    assert "Полбяная мука." in client.get(f"/recipes/{variant_id}").text


# --------------------------------------------------------------- read-only


def test_a_trashed_recipe_still_reads_in_full(client: TestClient) -> None:
    """You have to be able to look at it to decide whether to restore it."""
    recipe_id = _id(PIZZA)
    _delete(client, recipe_id)

    page = client.get(f"/recipes/{recipe_id}").text
    assert "Caputo 00" in page
    assert "In the trash" in page
    assert "restore it whenever you like" in page
    assert f"/recipes/{recipe_id}/restore" in page
    assert f"/recipes/{recipe_id}/purge" in page


def test_a_trashed_recipe_offers_nothing_that_changes_it(client: TestClient) -> None:
    recipe_id = _id(PIZZA)
    _delete(client, recipe_id)

    page = client.get(f"/recipes/{recipe_id}").text
    assert f"/recipes/{recipe_id}/edit" not in page
    assert f"/recipes/{recipe_id}/revise" not in page
    assert f"/recipes/{recipe_id}/ask" not in page


@pytest.mark.parametrize("path", ["edit", "revise"])
def test_the_write_screens_refuse_a_trashed_recipe(client: TestClient, path: str) -> None:
    """409, not 404: the recipe is right there, and the message says what to do."""
    recipe_id = _id(PIZZA)
    _delete(client, recipe_id)

    response = client.get(f"/recipes/{recipe_id}/{path}")
    assert response.status_code == 409
    assert "in the trash" in response.text


def test_editing_a_trashed_recipe_is_refused(client: TestClient) -> None:
    recipe_id = _id(PIZZA)
    _delete(client, recipe_id)

    response = client.post(
        f"/recipes/{recipe_id}/edit",
        data={
            "title": "Переименованная",
            "category": "Основные блюда",
            "hands_on_min": "40",
            "total_min": "180",
            "status": "new",
            "ingredients": "мука | 500 | г",
            "steps": "Замеси тесто.",
        },
    )
    assert response.status_code == 409
    assert _row(recipe_id).title == PIZZA


def test_asking_about_a_trashed_recipe_spends_nothing(client: TestClient) -> None:
    recipe_id = _id(PIZZA)
    _delete(client, recipe_id)

    response = client.post(f"/recipes/{recipe_id}/ask", data={"question": "Сколько муки?"})
    assert response.status_code == 409

    with Session(get_engine()) as session:
        assert session.query(LlmCall).count() == 0


# --------------------------------------------------------------- the domain


def test_move_to_trash_refuses_twice(session: Session) -> None:
    recipe = recipe_from_doc(demo_recipes()[0])
    session.add(recipe)
    session.flush()

    move_to_trash(session, recipe)
    with pytest.raises(TrashRefused):
        move_to_trash(session, recipe)


def test_purge_requires_the_trash_first(session: Session) -> None:
    """Enforced here and by a CHECK constraint, so nothing goes round the bin."""
    recipe = recipe_from_doc(demo_recipes()[0])
    session.add(recipe)
    session.flush()

    with pytest.raises(TrashRefused):
        purge(session, recipe)


def test_restore_refuses_a_purged_recipe(session: Session) -> None:
    recipe = recipe_from_doc(demo_recipes()[0])
    session.add(recipe)
    session.flush()

    move_to_trash(session, recipe)
    purge(session, recipe)
    with pytest.raises(TrashRefused):
        restore(session, recipe)


# --------------------------------------------------------------- the backup


def test_the_trash_survives_an_export_and_a_restore(session: Session) -> None:
    """A backup that resurrected everything you deleted would be a bad backup."""
    docs = demo_recipes()
    kept = recipe_from_doc(docs[0])
    binned = recipe_from_doc(docs[1])
    gone = recipe_from_doc(docs[2])
    session.add_all([kept, binned, gone])
    session.flush()

    move_to_trash(session, binned)
    move_to_trash(session, gone)
    purge(session, gone)
    session.flush()

    export = export_all(session)
    ids = (kept.id, binned.id, gone.id)

    session.query(Recipe).delete()
    session.flush()

    import_export(session, export)
    session.flush()

    restored = {r.id: r for r in session.scalars(select(Recipe).where(Recipe.id.in_(ids)))}
    assert restored[kept.id].deleted_at is None
    assert restored[binned.id].in_trash
    assert restored[gone.id].is_purged


def test_re_importing_the_same_file_changes_nothing(session: Session) -> None:
    """Merge is idempotent, and the deletion state must not break that."""
    recipe = recipe_from_doc(demo_recipes()[0])
    session.add(recipe)
    session.flush()
    move_to_trash(session, recipe)
    session.flush()

    export = export_all(session)
    report = import_export(session, export)
    assert (report.added, report.updated, report.skipped) == (0, 0, 1)


def test_undoing_a_variant_keeps_its_row(session: Session) -> None:
    """Undo removes the variant from the interface without dropping the row.

    The revision that created it points at that row, and so would anything the
    variant had become a parent of. Nothing here ever gets to leave a dangling
    reference behind.
    """

    original = recipe_from_doc(demo_recipes()[0])
    session.add(original)
    session.flush()

    after = RecipeDoc.model_validate(demo_variant_of_pizza().model_dump())
    revision = Revision(
        recipe_id=original.id,
        status="pending",
        origin="llm",
        instruction="замени треть муки на полбяную",
        before_snapshot=doc_to_dict(demo_recipes()[0]),
        after_snapshot=doc_to_dict(after),
    )
    session.add(revision)
    session.flush()

    variant = apply_as_variant(session, revision, original)
    session.flush()
    variant_id = variant.id

    undo(session, revision, original)
    session.flush()

    survivor = session.get(Recipe, variant_id)
    assert survivor is not None
    assert survivor.is_purged
