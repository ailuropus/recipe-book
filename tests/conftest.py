"""Database fixtures.

Everything runs against a throwaway `recipebook_test` database that is dropped
and recreated per session, and it is built by running the real Alembic
migrations rather than `create_all`. That way the migrations themselves are
under test — a migration that drifts from the models fails here rather than on
the VPS.
"""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from recipebook.config import Settings

TEST_DB_NAME = "recipebook_test"


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Drop and recreate the test database, then migrate it to head."""
    dev_url = make_url(Settings(_env_file=None).database_url)  # type: ignore[call-arg]
    admin_url = dev_url.set(database="postgres")

    try:
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        admin_engine.dispose()
    except OperationalError as exc:
        pytest.skip(f"Postgres unreachable ({exc.orig}); run `docker compose up -d db`")

    # render_as_string(hide_password=False), not str(): str() masks the password
    # as literal '***', which fails authentication in a very confusing way.
    test_url = dev_url.set(database=TEST_DB_NAME).render_as_string(hide_password=False)

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", test_url)
    command.upgrade(cfg, "head")

    return test_url


@pytest.fixture(scope="session")
def engine(test_database_url: str) -> Iterator[Engine]:
    # Point the application's own settings at the test database too, so code
    # under test that reaches for get_engine() lands in the right place.
    os.environ["DATABASE_URL"] = test_database_url

    eng = create_engine(test_database_url, future=True)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """One transaction per test, rolled back afterwards.

    Tests never see each other's rows, and the database does not need
    rebuilding between them.
    """
    connection = engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection, expire_on_commit=False)
    try:
        yield sess
    finally:
        sess.close()
        # Tests that deliberately provoke an IntegrityError have already had
        # their transaction torn down by the failed flush.
        if transaction.is_active:
            transaction.rollback()
        connection.close()
