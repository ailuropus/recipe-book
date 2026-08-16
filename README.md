# recipe-book

A personal recipe bank. Recipes are stored in a single house format, revised by
describing the change in plain words, and nothing is written until the change
has been reviewed as a diff.

Recipe content is in Russian. Interface chrome is in English.

## Development

Requires Python 3.13 and Docker.

Comments are on their own lines below: zsh does not strip a trailing `#` in an
interactive shell, so a copied line with one appended fails.

```sh
# then fill in ANTHROPIC_API_KEY from Bitwarden
cp .env.example .env
# Postgres 17 on localhost:5433
docker compose up -d db
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
# synthetic recipes, so there is something to look at
recipebook seed
# then open http://127.0.0.1:8000
uvicorn recipebook.web.app:app --reload
```

Postgres listens on **5433**, not 5432, so it cannot collide with a Postgres
already installed on the host.

Checks:

```sh
ruff check . && ruff format --check .
mypy
pytest                        # builds a throwaway recipebook_test database
```

`pytest` runs the real migrations against a scratch database, so a model
changed without a matching migration fails the suite. Schema changes always go
through `alembic revision --autogenerate -m "..."`, reviewed by hand before
committing.

## Reaching it from the phone

The app binds to `127.0.0.1:8000` and knows nothing about TLS. Tailscale fronts
it:

```sh
tailscale serve --bg 8000
```

That serves `https://<machine>.<tailnet>.ts.net` with a real certificate and
forwards to the local port. Works the same on the laptop today and on the VPS
later. No nginx, no certbot, and port 8000 is never exposed publicly.

## Two write paths

Small things are typed directly into the edit form, including ingredients,
equipment, and steps. Anything with knock-on effects — change a quantity and
the ingredient row, the step that uses it, and the notes all need to follow —
is described in words and applied only after the diff has been approved.

The form puts the structured sections into textareas using a line format that
round-trips exactly:

```
equipment     one per line   item | note
ingredients   one per line   name | qty | unit | note
steps         separated by a line containing only ---
```

Step numbering follows the order in the textarea, so deleting one renumbers the
rest.

## Adding a recipe

Paste anything into `/import` — prose, a list, a transcript. One LLM call
restructures it into the house format, and the result lands on a review screen
where every field is editable. **Nothing is written until you press save.**

What a good recipe contains lives in `llm/prompts.py`, not in the schema: the
schema can only say a step exists, not that it tells a beginner how to know the
onions are actually caramelised.

Every call records its token counts and a cost worked out at the time it was
made, in `llm_calls`. Rates are a snapshot, so an old row still means what it
meant when written. There are no quotas — the point is to see the spend.

## Language

Recipe content is Russian; interface chrome is English. Two tests hold the line:
`test_chrome_is_english.py` fails if Cyrillic appears in a template or a route,
and `test_recipe_voice.py` fails if recipe content addresses the cook formally.

**Recipes are на ты.** `Смешай`, not `Смешайте`. This is a content rule, so the
prompt that writes recipes is where it is really enforced; the test guards the
fixtures those prompts are calibrated against.

## Conventions

- Type hints throughout; `mypy` is strict on `domain/` and `llm/`.
- All schema changes are Alembic migrations. Nothing is applied by hand.
- Conventional commits, one per meaningful step.
- **Never commit real recipe content.** Development uses the synthetic
  fixtures in `tests/fixtures/`.
