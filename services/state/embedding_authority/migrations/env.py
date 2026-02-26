"""Alembic environment for Embedding Authority Service schema migrations."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from packages.brain_shared.config import load_settings
from resources.substrates.postgres.config import resolve_postgres_settings
from services.state.embedding_authority.data.runtime import embedding_postgres_schema
from services.state.embedding_authority.data.schema import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata

settings = load_settings()
postgres_settings = resolve_postgres_settings(settings)
sqlalchemy_url = postgres_settings.url
if not sqlalchemy_url:
    raise ValueError("components.substrate.postgres.url is required for EAS migrations")

schema_name = embedding_postgres_schema()
config.set_main_option("sqlalchemy.url", str(sqlalchemy_url))


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema=schema_name,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema=schema_name,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
