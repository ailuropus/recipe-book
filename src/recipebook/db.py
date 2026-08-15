"""Engine and session plumbing.

Synchronous on purpose. This is a single-user application; async buys nothing
here and costs a class of session-lifetime mistakes. FastAPI runs `def`
endpoints in a threadpool, so nothing blocks the event loop.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from recipebook.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def session_scope() -> Iterator[Session]:
    """FastAPI dependency and CLI helper.

    Commits on success, rolls back on any exception. The revision gate depends
    on this being all-or-nothing: a half-applied revision would leave a recipe
    inconsistent with its own audit log.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
