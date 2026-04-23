"""Alembic environment for Language Model Service schema."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from lib.shared.config import load_core_runtime_settings
from resources.substrates.postgres.config import resolve_postgres_settings
from services.action.language_model.data.runtime import language_model_postgres_schema
from services.action.language_model.data.schema import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata

settings = load_core_runtime_settings()
postgres_settings = resolve_postgres_settings(settings)
sqlalchemy_url = postgres_settings.url
if not sqlalchemy_url:
    raise ValueError("substrate.postgres.url is required for LMS migrations")

schema_name = language_model_postgres_schema()
config.set_main_option("sqlalchemy.url", str(sqlalchemy_url))


def _schema() -> str:
    """Return canonical LMS-owned schema name."""
    return schema_name


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=_schema(),
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=_schema(),
            include_schemas=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
