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

## Revising in words

`/recipes/<id>/revise` takes a plain-language instruction and returns a whole
revised recipe — whole, not a patch, because a change usually reaches several
places at once and they have to land together. The review screen shows what you
asked, what the model says it did, a field-by-field metadata table, and a
line diff of the recipe text with long unchanged runs collapsed.

The proposal is stored as a pending row and the browser is redirected to it, so
reloading the review page rereads a row rather than paying for the same call
twice. Nothing reaches the recipe until you post a decision.

Applying a change offers three outcomes: replace the recipe, keep both (the
revised version becomes a linked child, with the instruction as its variant
note), or discard.

## Undo

Every change is recorded, including edits typed into the form, and the most
recent one can be undone from the recipe's history. A replace is restored from
its before-snapshot. A variant is reversed by deleting the recipe it created —
but only while that recipe is still untouched; once it has been edited or given
variants of its own, undo refuses rather than deleting your work.

Only the most recent change is undoable. Restoring an older snapshot would
silently discard everything done since, which is not what anyone means by undo.

## Ask

The recipe page has a question box. It sends that recipe plus your question and
answers in Russian, на ты, citing the step a fact came from and saying plainly
when an answer is *not* from the recipe. It changes nothing and saves nothing —
if an answer is worth keeping, it belongs in the notes, which is an edit.

## What the calls cost

Measured on a real recipe:

| call     | cost   | time |
|----------|--------|------|
| import   | $0.073 | 48 s |
| revision | $0.147 | 74 s |
| ask      | $0.028 | 10 s |

Every call is logged to `llm_calls` with its token counts and the cost worked
out at the time. `select sum(cost_usd) from llm_calls where recipe_id = ...`
answers what a recipe has cost to perfect.

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
