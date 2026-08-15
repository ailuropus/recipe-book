# recipe-book

A personal recipe bank. Recipes are stored in a single house format, revised by
describing the change in plain words, and nothing is written until the change
has been reviewed as a diff.

Recipe content is in Russian. Interface chrome is in English.

## Development

Requires Python 3.13 and Docker.

```sh
cp .env.example .env          # then fill in ANTHROPIC_API_KEY from Bitwarden
docker compose up -d db       # Postgres 17 on localhost:5433
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
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

## Conventions

- Type hints throughout; `mypy` is strict on `domain/` and `llm/`.
- All schema changes are Alembic migrations. Nothing is applied by hand.
- Conventional commits, one per meaningful step.
- **Never commit real recipe content.** Development uses the synthetic
  fixtures in `tests/fixtures/`.
