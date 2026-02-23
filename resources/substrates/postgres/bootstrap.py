"""Pre-migration bootstrap for service schemas and shared SQL primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from packages.brain_shared.component_loader import import_registered_component_modules
from packages.brain_shared.config import BrainSettings, load_settings
from packages.brain_shared.ids.constants import ULID_DOMAIN_NAME
from packages.brain_shared.manifest import ServiceManifest, get_registry
from resources.substrates.postgres.config import resolve_postgres_settings
from resources.substrates.postgres.engine import create_postgres_engine

ULID_DOMAIN_DEFINITION_SQL = (
    f"CREATE DOMAIN IF NOT EXISTS {{schema}}.{ULID_DOMAIN_NAME} "
    "AS bytea CHECK (octet_length(VALUE) = 16)"
)


@dataclass(frozen=True)
class BootstrapResult:
    """Summary of pre-migration bootstrap actions."""

    imported_components: tuple[str, ...]
    provisioned_schemas: tuple[str, ...]


def bootstrap_service_schemas(
    settings: BrainSettings | None = None,
) -> BootstrapResult:
    """Provision all registered service schemas and shared SQL domains."""
    resolved_settings = load_settings() if settings is None else settings
    postgres_config = resolve_postgres_settings(resolved_settings)

    imported = import_registered_component_modules()
    registry = get_registry()
    registry.assert_valid()
    services = registry.list_services()
    if len(services) == 0:
        raise RuntimeError(
            "no registered services discovered; refusing schema bootstrap"
        )

    engine = create_postgres_engine(postgres_config)
    try:
        provisioned: list[str] = []
        with engine.begin() as connection:
            for service in services:
                _provision_service_schema(connection=connection, service=service)
                provisioned.append(service.schema_name)
    finally:
        engine.dispose()

    return BootstrapResult(
        imported_components=imported,
        provisioned_schemas=tuple(provisioned),
    )


def _provision_service_schema(*, connection: Any, service: ServiceManifest) -> None:
    """Create one service schema and bootstrap schema-local shared primitives."""
    schema = service.schema_name
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
    connection.execute(text(ULID_DOMAIN_DEFINITION_SQL.format(schema=schema)))


def main() -> None:
    """CLI entrypoint for migration bootstrap."""
    result = bootstrap_service_schemas()
    print(f"Imported {len(result.imported_components)} component module(s).")
    for module in result.imported_components:
        print(f"- {module}")
    print(f"Provisioned {len(result.provisioned_schemas)} schema(s).")
    for schema in result.provisioned_schemas:
        print(f"- {schema}")


if __name__ == "__main__":
    main()
