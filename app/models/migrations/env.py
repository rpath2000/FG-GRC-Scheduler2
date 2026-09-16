"""
Alembic environment script for the application's database migrations.

Imports the shared Base from app.models.database and reads the connection
URL from the app's own DATABASE_URL configuration (via app.db_url), never
constructing its own connection string.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db_url import DATABASE_URL
from app.models.database import Base
# Ensure all model modules are imported so Base.metadata is fully populated.
import app.models.models  # noqa: F401

config = context.config

# Configure logging from the .ini file's settings, WITHOUT disabling any
# loggers the application has already configured (startup may invoke
# alembic in-process via command.upgrade()).
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# Only fall back to the app's DATABASE_URL if the caller has not already
# set one explicitly (e.g. a test pointing alembic at its own database).
if not (config.get_main_option("sqlalchemy.url") or "").strip():
    # Double percent signs so configparser's interpolation does not choke
    # on a percent-encoded password or a `%3D`-style query string.
    config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section) or {}
    connectable = engine_from_config(
        configuration,
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
