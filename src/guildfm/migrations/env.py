from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, event, pool

from guildfm.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def database_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    from guildfm.config import get_settings

    return get_settings().sync_database_url


def run_migrations_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"sqlalchemy.url": database_url()}, prefix="sqlalchemy.", poolclass=pool.NullPool
    )

    # Python's sqlite3 commits schema changes as it goes, so a migration that failed halfway
    # used to leave half its tables behind. Taking charge of transactions makes each upgrade
    # all or nothing: SQLite can undo schema changes too.
    @event.listens_for(connectable, "connect")
    def _no_driver_transactions(dbapi_connection, _record) -> None:
        dbapi_connection.isolation_level = None

    @event.listens_for(connectable, "begin")
    def _begin(connection) -> None:
        connection.exec_driver_sql("BEGIN")

    with connectable.connect() as connection:
        # Batch mode lets Alembic alter tables on SQLite, which has limited ALTER TABLE support.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            transactional_ddl=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
