"""Web layer tests.

These exercise the routes through a real database so the search query, the
form round-trip, and the variant links are covered end to end.
"""

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from recipebook.db import get_engine, get_session_factory
from recipebook.demo import demo_recipes, demo_variant_of_pizza
from recipebook.mapping import recipe_from_doc
from recipebook.models import LlmCall, Recipe
from recipebook.schemas import Ingredient, Step
from recipebook.web.app import app
from tests.conftest import use_test_database


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    """A client wired to the test database, with the demo set loaded.

    The application's cached engine and session factory are rebuilt against the
    test database, then torn down, so this cannot leak into a later test.
    """
    use_test_database()

    with Session(engine) as setup:
        setup.query(LlmCall).delete()
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
        teardown.query(Recipe).delete()
        teardown.commit()

    get_engine.cache_clear()
    get_session_factory.cache_clear()


def _first_recipe_id(client: TestClient, title: str) -> str:
    with Session(get_engine()) as session:
        recipe = session.query(Recipe).filter(Recipe.title == title).one()
        return str(recipe.id)


def test_index_lists_recipes(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Пицца на тонком тесте" in response.text
    assert "Луковый суп" in response.text


def test_index_search_uses_russian_stemming(client: TestClient) -> None:
    """The payoff of the 'russian' config, reached through the actual route."""
    response = client.get("/", params={"q": "луковый"})
    assert response.status_code == 200
    assert "Луковый суп" in response.text
    assert "Овсяная каша на ночь" not in response.text


def test_index_search_finds_a_word_only_present_in_a_step(client: TestClient) -> None:
    response = client.get("/", params={"q": "карамелизация"})
    assert "Луковый суп" in response.text


def test_index_filters_by_category(client: TestClient) -> None:
    response = client.get("/", params={"category": "Супы"})
    assert "Луковый суп" in response.text
    assert "Овсяная каша на ночь" not in response.text


def test_index_filters_by_status(client: TestClient) -> None:
    response = client.get("/", params={"status": "new"})
    assert "Овсяная каша на ночь" in response.text
    assert "Луковый суп" not in response.text


def test_index_reports_no_matches(client: TestClient) -> None:
    response = client.get("/", params={"q": "вертолёт"})
    assert "Nothing matches." in response.text


def test_detail_renders_the_recipe(client: TestClient) -> None:
    recipe_id = _first_recipe_id(client, "Пицца на тонком тесте")
    response = client.get(f"/recipes/{recipe_id}")

    assert response.status_code == 200
    assert "Caputo 00" in response.text
    assert "Камень для пиццы" in response.text
    # Step markdown is rendered, not shown raw.
    assert "перестаёт липнуть к рукам" in response.text


def test_plan_ahead_is_called_out_on_the_detail_page(client: TestClient) -> None:
    """The one thing the warning colour is allowed to mean."""
    recipe_id = _first_recipe_id(client, "Пицца на тонком тесте")
    assert "plan-ahead-callout" in client.get(f"/recipes/{recipe_id}").text

    soup_id = _first_recipe_id(client, "Луковый суп")
    assert "plan-ahead-callout" not in client.get(f"/recipes/{soup_id}").text


def test_variant_links_navigate_both_directions(client: TestClient) -> None:
    parent_id = _first_recipe_id(client, "Пицца на тонком тесте")
    variant_id = _first_recipe_id(client, "Пицца на тонком тесте — на полбяной муке")

    parent_page = client.get(f"/recipes/{parent_id}").text
    assert f"/recipes/{variant_id}" in parent_page

    variant_page = client.get(f"/recipes/{variant_id}").text
    assert f"/recipes/{parent_id}" in variant_page
    assert "Полбяная мука." in variant_page


def test_unknown_recipe_returns_404_page(client: TestClient) -> None:
    response = client.get("/recipes/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert "No such recipe" in response.text


def _porridge_form(**overrides: str) -> dict[str, str]:
    """The porridge recipe as the edit form submits it.

    A browser posts every field it renders, so a test that omits one is testing
    something the application never sees.
    """
    data = {
        "title": "Овсяная каша на ночь",
        "category": "Завтраки",
        "description": "Собирается вечером.",
        "servings": "2 порции",
        "hands_on_min": "7",
        "total_min": "600",
        "status": "tried",
        "equipment": "Банка с крышкой | около 500 мл",
        "ingredients": (
            "овсяные хлопья | 50 | г | не быстрого приготовления\n"
            "молоко | 150 | мл | жирность 3,2%\n"
            "мёд | 1 | ст.л."
        ),
        "steps": (
            "Смешай всё в банке, закрой и убери в холодильник.\n"
            "---\n"
            "Утром перемешай. Каша должна быть густой, но не сухой."
        ),
        "notes_md": "С мёдом заметно лучше.",
        "plan_ahead": "true",
    }
    data.update(overrides)
    return data


def test_edit_form_round_trip(client: TestClient) -> None:
    recipe_id = _first_recipe_id(client, "Овсяная каша на ночь")

    form = client.get(f"/recipes/{recipe_id}/edit")
    assert form.status_code == 200

    response = client.post(
        f"/recipes/{recipe_id}/edit", data=_porridge_form(), follow_redirects=False
    )
    assert response.status_code == 303

    detail = client.get(f"/recipes/{recipe_id}").text
    assert "2 порции" in detail
    assert "С мёдом заметно лучше." in detail
    assert "tried" in detail


def test_edit_form_exposes_the_body_sections(client: TestClient) -> None:
    recipe_id = _first_recipe_id(client, "Луковый суп")
    form = client.get(f"/recipes/{recipe_id}/edit").text

    assert 'name="steps"' in form
    assert 'name="ingredients"' in form
    assert 'name="equipment"' in form
    # Rendered in the textarea encoding, not as JSON.
    assert "лук репчатый | 1 | кг | жёлтый, не сладкий" in form


def test_editing_a_step_changes_the_recipe_and_the_search_index(client: TestClient) -> None:
    """A hand edit to a step is a real edit: it reaches the page and the index."""
    recipe_id = _first_recipe_id(client, "Овсяная каша на ночь")

    client.post(
        f"/recipes/{recipe_id}/edit",
        data=_porridge_form(
            steps=(
                "Смешай всё в банке, закрой и убери в холодильник.\n"
                "---\n"
                "Утром перемешай и добавь горсть черники."
            )
        ),
        follow_redirects=False,
    )

    assert "горсть черники" in client.get(f"/recipes/{recipe_id}").text
    assert "Овсяная каша на ночь" in client.get("/", params={"q": "черника"}).text


def test_removing_an_ingredient_removes_it(client: TestClient) -> None:
    recipe_id = _first_recipe_id(client, "Овсяная каша на ночь")

    client.post(
        f"/recipes/{recipe_id}/edit",
        data=_porridge_form(ingredients="овсяные хлопья | 50 | г\nмолоко | 150 | мл"),
        follow_redirects=False,
    )

    detail = client.get(f"/recipes/{recipe_id}").text
    # The notes still say "с мёдом", so look for the ingredient row itself.
    assert "ст.л." not in detail
    assert "овсяные хлопья" in detail


def test_a_malformed_ingredient_line_is_rejected_without_writing(client: TestClient) -> None:
    """The parse happens before anything is assigned, so a bad line changes nothing."""
    recipe_id = _first_recipe_id(client, "Овсяная каша на ночь")

    response = client.post(
        f"/recipes/{recipe_id}/edit",
        data=_porridge_form(
            title="Каша, переименованная",
            ingredients="мёд | 1 | ст.л. | липовый | лишнее поле",
        ),
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "Line 1" in response.text
    # The rejected input comes back in the form rather than being thrown away.
    assert "лишнее поле" in response.text

    detail = client.get(f"/recipes/{recipe_id}").text
    assert "Каша, переименованная" not in detail
    assert "овсяные хлопья" in detail


def test_unchecked_plan_ahead_clears_the_flag(client: TestClient) -> None:
    """An unchecked checkbox sends nothing at all, which is exactly the case a
    naive form handler gets wrong."""
    recipe_id = _first_recipe_id(client, "Овсяная каша на ночь")

    form = _porridge_form()
    del form["plan_ahead"]
    client.post(f"/recipes/{recipe_id}/edit", data=form, follow_redirects=False)

    assert "plan-ahead-callout" not in client.get(f"/recipes/{recipe_id}").text


def test_import_form_renders(client: TestClient) -> None:
    response = client.get("/import")
    assert response.status_code == 200
    assert 'name="raw"' in response.text


def test_import_shows_a_review_and_saves_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate: the model has answered, and still nothing is in the database."""
    from recipebook.llm.importer import ImportResult
    from recipebook.schemas import RecipeDoc

    doc = RecipeDoc(
        title="Сырники",
        category="Завтраки",
        description="Творожные оладьи на завтрак.",
        hands_on_min=20,
        total_min=25,
        servings="2 порции",
        plan_ahead=False,
        ingredients=[Ingredient(name="творог", qty="400", unit="г", note="жирность 9%")],
        steps=[Step(n=1, text_md="Разотри творог вилкой до однородности.")],
    )
    monkeypatch.setattr(
        "recipebook.web.routes_import.import_recipe",
        lambda session, raw: ImportResult(doc=doc, llm_call_id=uuid.uuid4(), cost_usd="0.0312"),
    )

    response = client.post("/import", data={"raw": "творог, яйцо, мука"})

    assert response.status_code == 200
    assert "Сырники" in response.text
    assert "творог | 400 | г | жирность 9%" in response.text
    assert "0.0312" in response.text

    with Session(get_engine()) as session:
        assert session.query(Recipe).filter(Recipe.title == "Сырники").count() == 0


def test_saving_a_reviewed_import_creates_the_recipe(client: TestClient) -> None:
    response = client.post(
        "/import/save",
        data={
            "title": "Сырники",
            "category": "Завтраки",
            "description": "Творожные оладьи на завтрак.",
            "servings": "2 порции",
            "hands_on_min": "20",
            "total_min": "25",
            "status": "new",
            "equipment": "",
            "ingredients": "творог | 400 | г | жирность 9%",
            "steps": "Разотри творог вилкой до однородности.",
            "notes_md": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    detail = client.get(response.headers["location"]).text
    assert "Сырники" in detail
    assert "жирность 9%" in detail


def test_saving_attaches_the_import_cost_to_the_new_recipe(client: TestClient) -> None:
    """An import call is made before the recipe exists; the save links them up."""
    with Session(get_engine()) as setup:
        call = LlmCall(kind="import", model="claude-opus-5", cost_usd=Decimal("0.0312"))
        setup.add(call)
        setup.commit()
        call_id = call.id

    response = client.post(
        "/import/save",
        data={
            "title": "Сырники",
            "category": "Завтраки",
            "hands_on_min": "20",
            "total_min": "25",
            "status": "new",
            "ingredients": "творог | 400 | г",
            "steps": "Разотри творог вилкой.",
            "llm_call_id": str(call_id),
        },
        follow_redirects=False,
    )
    recipe_id = uuid.UUID(response.headers["location"].rsplit("/", 1)[1])

    with Session(get_engine()) as check:
        saved = check.get(LlmCall, call_id)
        assert saved is not None
        assert saved.recipe_id == recipe_id


def test_a_bad_line_in_the_review_saves_nothing(client: TestClient) -> None:
    response = client.post(
        "/import/save",
        data={
            "title": "Сырники",
            "category": "Завтраки",
            "hands_on_min": "20",
            "total_min": "25",
            "status": "new",
            "ingredients": "творог | 400 | г | 9% | лишнее",
            "steps": "Разотри творог вилкой.",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "Line 1" in response.text

    with Session(get_engine()) as check:
        assert check.query(Recipe).filter(Recipe.title == "Сырники").count() == 0


def test_import_reports_a_missing_api_key_plainly(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a key this is the first thing that happens, so it must not 500."""

    def blow_up(session: object, raw: str) -> None:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    monkeypatch.setattr("recipebook.web.routes_import.import_recipe", blow_up)

    response = client.post("/import", data={"raw": "творог"})
    assert response.status_code == 400
    assert "ANTHROPIC_API_KEY is not set." in response.text
    # The paste comes back rather than being thrown away.
    assert "творог" in response.text


def test_slow_forms_are_marked_for_the_waiting_room(client: TestClient) -> None:
    """The three forms that call the model, and only those."""
    assert 'data-busy="Reading your recipe' in client.get("/import").text

    recipe_id = _first_recipe_id(client, "Луковый суп")
    assert 'data-busy="Working out the change' in client.get(f"/recipes/{recipe_id}/revise").text
    assert 'data-busy="Thinking' in client.get(f"/recipes/{recipe_id}").text

    # The plain edit form is fast and must not put up an overlay.
    assert "data-busy" not in client.get(f"/recipes/{recipe_id}/edit").text


def test_the_waiting_room_is_hidden_until_javascript_shows_it(client: TestClient) -> None:
    page = client.get("/import").text
    assert '<div class="busy" id="busy" hidden' in page
    assert "/static/app.js" in page


def test_a_missing_clip_falls_back_to_the_mouse(client: TestClient) -> None:
    """Dropping in static/processing.mp4 swaps this for the video; without the
    file there must be no broken <video> element."""
    from recipebook.web.templating import BUSY_CLIP

    page = client.get("/import").text
    if BUSY_CLIP.exists():
        assert "processing.mp4" in page
    else:
        assert "<video" not in page
        assert 'class="busy__clip" src="/static/mouse.png"' in page


def test_the_brand_is_two_images_and_no_text(client: TestClient) -> None:
    page = client.get("/").text
    assert "/static/mouse.png" in page
    assert "/static/wordmark.png" in page
    assert "masthead__name" not in page


def test_the_index_greets_you(client: TestClient) -> None:
    page = client.get("/").text
    assert "cook something Maus" in page
    assert 'class="hero__mouse"' in page
