"""Shared Postgres substrate primitives for Brain services."""

from resources.substrates.postgres.component import MANIFEST, RESOURCE_COMPONENT_ID
from resources.substrates.postgres.config import PostgresSettings
from resources.substrates.postgres.engine import create_postgres_engine
from resources.substrates.postgres.errors import normalize_postgres_error
from resources.substrates.postgres.health import ping
from resources.substrates.postgres.bootstrap import bootstrap_service_schemas
from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
from resources.substrates.postgres.session import (
    create_session_factory,
    transactional_session,
)

__all__ = [
    "MANIFEST",
    "RESOURCE_COMPONENT_ID",
    "PostgresSettings",
    "create_postgres_engine",
    "bootstrap_service_schemas",
    "create_session_factory",
    "transactional_session",
    "ServiceSchemaSessionProvider",
    "normalize_postgres_error",
    "ping",
]
