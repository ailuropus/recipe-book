"""Web layer tests.

These exercise the routes through a real database so the search query, the
form round-trip, and the variant links are covered end to end.
"""

import uuid
from collections.abc import Iterator
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from recipebook.db import get_engine, get_session_factory
from recipebook.demo import demo_recipes, demo_variant_of_pizza
from recipebook.mapping import recipe_from_doc
from recipebook.models import Job, LlmCall, Recipe
from recipebook.schemas import Ingredient, RecipeDoc, Step
from recipebook.web.app import app
from recipebook.web.templating import STATIC_DIR
from tests.conftest import use_test_database
from tests.fake_anthropic import fake_client


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    """A client wired to the test database, with the demo set loaded.

    The application's cached engine and session factory are rebuilt against the
    test database, then torn down, so this cannot leak into a later test.
    """
    use_test_database()

    with Session(engine) as setup:
        setup.query(Job).delete()
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
        teardown.query(Job).delete()
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


def _syrniki() -> RecipeDoc:
    return RecipeDoc(
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


def _fake_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real importer, talking to a fake model, so the cost row is real."""
    from recipebook.llm.importer import import_recipe

    fake, _ = fake_client(_syrniki())
    monkeypatch.setattr(
        "recipebook.web.routes_import.import_recipe",
        lambda session, raw: import_recipe(session, raw, client=fake),
    )


def _start_import(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> str:
    """Post a paste and return the job URL the browser is sent to wait on."""
    _fake_import(monkeypatch)
    response = client.post("/import", data={"raw": "творог, яйцо, мука"}, follow_redirects=False)
    assert response.status_code == 303
    location = str(response.headers["location"])
    assert location.startswith("/jobs/")
    return location


def test_import_shows_a_review_and_saves_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate: the model has answered, and still nothing is in the database."""
    _fake_import(monkeypatch)

    response = client.post("/import", data={"raw": "творог, яйцо, мука"})

    assert response.status_code == 200
    assert response.url.path.startswith("/imports/")
    assert "Сырники" in response.text
    assert "творог | 400 | г | жирность 9%" in response.text
    # 1200 in at $5, 800 cache reads at $0.50, 900 out at $25, per million.
    assert "0.0289" in response.text

    with Session(get_engine()) as session:
        assert session.query(Recipe).filter(Recipe.title == "Сырники").count() == 0


def test_starting_an_import_returns_before_the_call_is_made(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The post only writes the job down. The call belongs to the job, not to
    the request, which is what lets the browser leave without losing it."""
    started: list[object] = []
    monkeypatch.setattr(
        "recipebook.web.background.start", lambda target, *args: started.append(args)
    )

    response = client.post("/import", data={"raw": "творог"}, follow_redirects=False)

    assert response.status_code == 303
    assert len(started) == 1
    page = client.get(response.headers["location"]).text
    assert "Reading your recipe" in page
    assert "data-job-status" in page
    assert "You can close this page" in page

    with Session(get_engine()) as check:
        job = check.query(Job).one()
        assert job.status == "running"
        assert job.input == "творог"


def test_the_waiting_page_reports_its_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    location = _start_import(client, monkeypatch)

    status = client.get(f"{location}/status").json()
    assert status["status"] == "done"
    assert status["url"].startswith("/imports/")


def test_a_running_job_tells_the_page_to_keep_waiting(client: TestClient) -> None:
    with Session(get_engine()) as setup:
        job = Job(kind="import", input="творог")
        setup.add(job)
        setup.commit()
        job_id = job.id

    assert client.get(f"/jobs/{job_id}/status").json() == {
        "status": "running",
        "url": f"/jobs/{job_id}",
    }
    page = client.get(f"/jobs/{job_id}").text
    assert "<video" in page and "autoplay" in page


def test_a_closed_tab_loses_nothing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Start an import and never come back to the waiting page: the result is
    on the index, and opening it costs nothing more."""
    _start_import(client, monkeypatch)

    index = client.get("/").text
    assert "Waiting for you" in index
    assert "ready to review" in index
    assert "Сырники" in index

    review = client.get("/").text.split('href="/imports/', 1)[1].split('"', 1)[0]
    for _ in range(3):
        page = client.get(f"/imports/{review}")
        assert page.status_code == 200
        assert "Сырники" in page.text

    with Session(get_engine()) as check:
        assert check.query(LlmCall).count() == 1


def _save_review(client: TestClient, job_url: str) -> httpx.Response:
    job_id = job_url.rsplit("/", 1)[1]
    with Session(get_engine()) as read:
        job = read.get(Job, uuid.UUID(job_id))
        assert job is not None
        call_id = str(job.llm_call_id)
    response: httpx.Response = client.post(
        "/import/save",
        data={
            "title": "Сырники",
            "category": "Завтраки",
            "hands_on_min": "20",
            "total_min": "25",
            "status": "new",
            "ingredients": "творог | 400 | г",
            "steps": "Разотри творог вилкой.",
            "llm_call_id": call_id,
            "job_id": job_id,
        },
        follow_redirects=False,
    )
    return response


def test_saving_an_import_takes_it_off_the_waiting_list(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    location = _start_import(client, monkeypatch)
    response = _save_review(client, location)
    assert response.status_code == 303

    assert "Waiting for you" not in client.get("/").text


def test_saving_the_same_import_twice_makes_one_recipe(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Back button, save again: the second press lands on the first recipe."""
    location = _start_import(client, monkeypatch)
    first = _save_review(client, location)
    second = _save_review(client, location)

    assert first.headers["location"] == second.headers["location"]
    with Session(get_engine()) as check:
        assert check.query(Recipe).filter(Recipe.title == "Сырники").count() == 1

    # And the review itself now points at what it became.
    job_id = location.rsplit("/", 1)[1]
    again = client.get(f"/imports/{job_id}", follow_redirects=False)
    assert again.headers["location"] == first.headers["location"]


def test_discarding_an_import_takes_it_off_the_waiting_list(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    location = _start_import(client, monkeypatch)
    job_id = location.rsplit("/", 1)[1]

    review = client.get(location).text
    assert f'action="/jobs/{job_id}/dismiss"' in review

    response = client.post(f"/jobs/{job_id}/dismiss", follow_redirects=False)
    assert response.status_code == 303
    assert "Waiting for you" not in client.get("/").text

    with Session(get_engine()) as check:
        assert check.query(Recipe).filter(Recipe.title == "Сырники").count() == 0


def test_an_empty_paste_is_refused_without_starting_anything(client: TestClient) -> None:
    response = client.post("/import", data={"raw": "   "})
    assert response.status_code == 400
    assert "Nothing was pasted." in response.text

    with Session(get_engine()) as check:
        assert check.query(Job).count() == 0


def test_a_restart_fails_the_jobs_it_interrupted(client: TestClient) -> None:
    """The call ran on a thread that died with the process. Without this the
    waiting page would wait forever."""
    from recipebook.domain.jobs import INTERRUPTED

    with Session(get_engine()) as setup:
        job = Job(kind="import", input="творог")
        setup.add(job)
        setup.commit()
        job_id = job.id

    with TestClient(app):
        pass

    with Session(get_engine()) as check:
        interrupted = check.get(Job, job_id)
        assert interrupted is not None
        assert interrupted.status == "failed"
        assert interrupted.error == INTERRUPTED

    page = client.get(f"/jobs/{job_id}").text
    assert "server restarted" in page
    assert "творог" in page


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


def test_the_app_starts_before_the_jobs_table_exists(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deploy rebuilds, then migrates with `docker compose exec`. If startup
    failed on the missing table, the container would restart forever and the
    exec that runs the migration would have nothing to run in."""
    from sqlalchemy.exc import ProgrammingError

    def no_table(session: object) -> int:
        raise ProgrammingError("SELECT ...", {}, Exception('relation "jobs" does not exist'))

    monkeypatch.setattr("recipebook.web.app.interrupt_running", no_table)

    with TestClient(app) as fresh:
        assert fresh.get("/import").status_code == 200


def test_import_reports_a_missing_api_key_plainly(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a key this is the first thing that happens, so it must not 500."""

    def blow_up(session: object, raw: str) -> None:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    monkeypatch.setattr("recipebook.web.routes_import.import_recipe", blow_up)

    response = client.post("/import", data={"raw": "творог"})
    assert response.status_code == 200
    assert "ANTHROPIC_API_KEY is not set." in response.text
    # The paste comes back rather than being thrown away.
    assert "творог" in response.text


def test_a_failed_import_waits_on_the_index_until_retried(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def blow_up(session: object, raw: str) -> None:
        raise RuntimeError("overloaded")

    monkeypatch.setattr("recipebook.web.routes_import.import_recipe", blow_up)
    failed = client.post("/import", data={"raw": "творог"})
    job_id = failed.url.path.rsplit("/", 1)[1]
    assert f'name="retry_of" value="{job_id}"' in failed.text

    index = client.get("/").text
    assert "failed" in index
    assert "творог" in index

    _fake_import(monkeypatch)
    client.post("/import", data={"raw": "творог", "retry_of": job_id})

    with Session(get_engine()) as check:
        job = check.get(Job, uuid.UUID(job_id))
        assert job is not None
        assert job.closed_at is not None


def test_slow_forms_are_marked_for_the_waiting_room(client: TestClient) -> None:
    """The three forms that call the model, and only those.

    Import and revise start a job and redirect to a page that waits on it, so
    they only refuse a second press. The question holds the request open, so
    it puts up the overlay.
    """
    import_page = client.get("/import").text
    assert "data-once" in import_page
    assert "data-busy" not in import_page.split("<form", 1)[1].split(">", 1)[0]

    recipe_id = _first_recipe_id(client, "Луковый суп")
    assert "data-once" in client.get(f"/recipes/{recipe_id}/revise").text
    assert 'data-busy="Thinking' in client.get(f"/recipes/{recipe_id}").text

    # The plain edit form is fast and must not put up an overlay.
    assert "data-busy" not in client.get(f"/recipes/{recipe_id}/edit").text


def test_the_waiting_room_is_hidden_until_javascript_shows_it(client: TestClient) -> None:
    page = client.get("/import").text
    assert '<div class="busy" id="busy" hidden' in page
    assert "/static/app.js" in page


def test_a_missing_clip_falls_back_to_the_mouse(client: TestClient) -> None:
    """Every clip format present becomes a <source>; none of them present must
    leave a still mouse rather than a broken <video> element."""
    from recipebook.web.templating import busy_clip_sources

    page = client.get("/import").text
    sources = busy_clip_sources()
    if sources:
        assert "<video" in page
        for source in sources:
            assert f'src="{source["src"]}" type="{source["type"]}"' in page
    else:
        assert "<video" not in page
        assert 'class="busy__clip" src="/static/mouse.png"' in page


def test_the_running_mouse_is_offered_in_both_formats(client: TestClient) -> None:
    """WebM first so a browser that can take it never fetches the larger mp4."""
    page = client.get("/import").text
    assert page.index("running_mausi.webm") < page.index("running_mausi.mp4")


def test_the_brand_is_two_images_and_no_text(client: TestClient) -> None:
    page = client.get("/").text
    assert "/static/mouse.png" in page
    assert "/static/wordmark.png" in page
    assert "masthead__name" not in page


def test_the_index_greets_you(client: TestClient) -> None:
    page = client.get("/").text
    assert "cook something Maus" in page
    assert 'class="hero__mouse"' in page


def test_static_urls_carry_a_fingerprint(client: TestClient) -> None:
    """A stylesheet whose URL never changes is a stylesheet a browser keeps.

    This is what stopped a deploy reaching the phone: new markup arrived with
    the previous release's CSS still cached against it.
    """
    import re

    page = client.get("/").text
    match = re.search(r'href="(/static/app\.css\?v=[0-9a-f]+)"', page)
    assert match, "the stylesheet is linked without a fingerprint"

    response = client.get(match.group(1))
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


def test_the_fingerprint_follows_the_file(client: TestClient) -> None:
    from recipebook.web.templating import static_url

    before = static_url("app.css")
    path = STATIC_DIR / "app.css"
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"\n/* touched */\n")
        assert static_url("app.css") != before
    finally:
        path.write_bytes(original)


def test_an_unfingerprinted_static_request_is_left_to_the_browser(
    client: TestClient,
) -> None:
    """No header rather than a wrong one: this is a hand-typed or stale URL."""
    response = client.get("/static/app.css")
    assert response.status_code == 200
    assert "immutable" not in response.headers.get("cache-control", "")


def test_pages_are_never_cached(client: TestClient) -> None:
    assert "no-store" in client.get("/").headers["cache-control"]
