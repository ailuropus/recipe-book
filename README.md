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

Putting it on the netcup box: **[DEPLOY.md](DEPLOY.md)**.

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
where every field is editable. **No recipe is written until you press save.**

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

The proposal is stored as a pending row, so reloading the review page rereads
a row rather than paying for the same call twice. Nothing reaches the recipe
until you post a decision.

## Slow calls survive a closed tab

An import takes about fifty seconds and a revision about seventy-five, which is
too long to hold a form post open: a locked phone or a dropped connection would
throw away a call that has already been paid for. So neither one runs inside
the request.

Submitting the form writes a row to `jobs` and redirects at once to
`/jobs/<id>`. The call runs on a thread in the server and writes its result to
that row whether or not a browser is still watching. The page at `/jobs/<id>`
waits while the job runs, redirects to the review once it is done, and shows
the form again — filled in, with the reason — if it failed. It is safe to
reload, to leave, and to come back to.

Anything still running, ready to review, or failed is listed under **Waiting
for you** on the index until it has been dealt with: an import saved or
discarded, a proposal decided, a failure retried or dismissed. That list is
how a result left behind in a closed tab is found again.

A restart kills the threads with it, so on startup every job still marked
running is failed with a message saying so, rather than leaving a waiting page
that never stops waiting. This assumes one server process, which is how the
app runs; with several, one starting up would fail jobs another is working on.

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

## Deleting

Delete is one press on the recipe page and asks nothing, because it is not
final. The recipe moves to the trash, the index that follows carries a shield
naming it with a restore button and a bar draining through the ten seconds it
stays, and after that it is still in **/trash** until you say otherwise.

Deleted recipes are out of the index, out of search, and out of the category
list. They are not out of the database. There are two steps and neither one
removes the row:

| state         | `deleted_at` | `purged_at` | where it appears |
|---------------|--------------|-------------|------------------|
| in the bank   | —            | —           | index, search, lineage |
| in the trash  | set          | —           | /trash, and its own page |
| deleted forever | set        | set         | nowhere |

**Delete forever keeps the row too.** `recipes.parent_id` points at it, and
`ON DELETE SET NULL` means a real `DELETE` would take the parent link off every
variant of that recipe — a variant that can no longer say where it came from
has lost something the trash was never asked to take. So the row survives as an
anchor: the link stays in the database and the interface stops drawing it.

A recipe in the trash still reads in full, because deciding whether to restore
it means looking at it. What it does not have is any way to change it: revise,
edit, and ask are gone from the page and refused by the routes with a 409 that
says to restore it first. Spending a model call on a recipe that is not in the
bank is never what anyone meant.

Deleting moves one recipe and never a family. Its variants stay in the index
and say **variant of &lt;name&gt; (deleted)** — the lineage is a fact about the
variant, not about what is currently on screen. Restoring the parent puts the
line back to normal; deleting it forever takes the line away entirely.

Nothing in the trash expires on a timer. A recipe leaves that list because you
restored it or because you said forever, never because a fortnight passed.

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

## Export, import, backup

```sh
recipebook export -o bank.json     # or omit -o for stdout
recipebook import bank.json        # merges by id
recipebook backup --dir backups --keep 14
recipebook spend                   # what the calls have cost, per recipe
```

The JSON carries recipes with their ids, their parent links, and their deletion
state, so a restore rebuilds the bank with its lineage and its trash intact —
a backup that quietly resurrected everything you had deleted would be a bad
backup. That is what took the file to format version 2; a version 1 file still
loads, and reads as a bank with nothing deleted. It deliberately does **not** carry
revisions or the cost log — that is how a recipe got here, not the recipe, and
leaving it out keeps a restore from resurrecting a pending review.

`import` merges by id: re-running the same file is a no-op, a changed recipe is
updated in place, and anything the file does not mention is **left alone**.
`--mode replace` deletes those instead; merge is the default because an import
is usually a restore, and quietly deleting recipes is the worst thing it could
do. A file whose children are listed before their parents still loads — links
are resolved on a second pass — and a parent that is nowhere becomes an orphan
rather than failing the whole import.

This is not a substitute for `pg_dump`, which is still the way to take
everything. It is the copy that survives a schema change or a move to another
machine.

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
