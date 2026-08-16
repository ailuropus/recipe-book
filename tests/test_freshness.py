"""A page must never show what the last write replaced.

Two independent causes of the same symptom — a page that looks unchanged until
you refresh — and both are covered here because fixing one would have left the
other in place.
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from recipebook.db import get_engine, get_session_factory
from recipebook.mapping import recipe_from_doc
from recipebook.models import LlmCall, Recipe, Revision
from recipebook.web.app import app
from recipebook.web.responses import see_other
from tests.conftest import use_test_database
from tests.fixtures import pizza


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    use_test_database()
    with Session(engine) as setup:
        setup.query(LlmCall).delete()
        setup.query(Revision).delete()
        setup.query(Recipe).delete()
        setup.add(recipe_from_doc(pizza()))
        setup.commit()

    with TestClient(app) as test_client:
        yield test_client

    with Session(engine) as teardown:
        teardown.query(LlmCall).delete()
        teardown.query(Revision).delete()
        teardown.query(Recipe).delete()
        teardown.commit()


def _pizza_id() -> uuid.UUID:
    with Session(get_engine()) as session:
        return session.query(Recipe).filter(Recipe.title == pizza().title).one().id


def test_see_other_commits_before_it_returns() -> None:
    """The point of the helper.

    Visibility is checked from a second, independent connection, because that
    is what the browser's next request will use. Leaving the commit to the
    session dependency makes this fail: the redirect goes out first and the
    write lands after.
    """
    factory = get_session_factory()
    session = factory()
    try:
        recipe = recipe_from_doc(pizza())
        recipe.title = "Записано до редиректа"
        session.add(recipe)

        response = see_other(session, "/somewhere")
        assert response.status_code == 303

        with Session(get_engine()) as other_connection:
            found = other_connection.scalars(
                select(Recipe).where(Recipe.title == "Записано до редиректа")
            ).one_or_none()
            assert found is not None, "the write had not landed when the redirect was returned"
    finally:
        with Session(get_engine()) as cleanup:
            cleanup.query(Recipe).filter(Recipe.title == "Записано до редиректа").delete()
            cleanup.commit()
        session.close()


def test_an_edit_is_visible_on_the_very_next_request(client: TestClient) -> None:
    recipe_id = _pizza_id()
    client.post(
        f"/recipes/{recipe_id}/edit",
        data={
            "title": "Пицца на тонком тесте",
            "category": "Основные блюда",
            "hands_on_min": "40",
            "total_min": "180",
            "status": "solid",
            "ingredients": "мука | 500 | г",
            "steps": "Замеси тесто.",
            "notes_md": "Свежая заметка.",
        },
        follow_redirects=False,
    )
    assert "Свежая заметка." in client.get(f"/recipes/{recipe_id}").text


def test_html_pages_are_never_cached(client: TestClient) -> None:
    for path in ("/", f"/recipes/{_pizza_id()}", "/import"):
        cache_control = client.get(path).headers.get("cache-control", "")
        assert "no-store" in cache_control, f"{path} may be served from cache"


def test_static_assets_stay_cacheable(client: TestClient) -> None:
    """The one thing worth caching: it only changes when the file does."""
    assert "no-store" not in client.get("/static/app.css").headers.get("cache-control", "")
