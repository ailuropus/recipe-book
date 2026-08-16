from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from recipebook.config import get_settings
from recipebook.models import Base

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False, unlike the Alembic default. Migrations
    # run in-process from the test suite and could run from the CLI, and the
    # default silences every logger that already exists — including the app's
    # own cost logging, which then just stops appearing with no error anywhere.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# One source of truth for the connection string: the environment, via config.py.
# Unless a caller has already set one — the test suite points migrations at a
# throwaway database, and must not be able to touch the development one.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
