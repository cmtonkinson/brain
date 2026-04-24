"""SQLAlchemy helpers for ULID-backed primary keys."""

from __future__ import annotations

from sqlalchemy import Column
from sqlalchemy.dialects import postgresql

from lib.shared.ids.constants import ULID_DOMAIN_NAME


def ulid_domain_type(schema_name: str) -> postgresql.DOMAIN:
    """Return a schema-local ``ulid_bin`` PostgreSQL domain reference.

    The domain itself is created by Postgres bootstrap; callers reference it
    here in schema/migration definitions with ``create_type=False``.
    """
    if not schema_name:
        raise ValueError("schema_name is required for ulid_domain_type")
    return postgresql.DOMAIN(
        name=ULID_DOMAIN_NAME,
        data_type=postgresql.BYTEA(),
        schema=schema_name,
        create_type=False,
    )


def ulid_primary_key_column(
    name: str = "id",
    schema_name: str | None = None,
) -> Column[bytes]:
    """Return a standard ULID primary-key column definition.

    Uses schema-local PostgreSQL ``ulid_bin`` domain to represent canonical
    128-bit ULIDs generated in application code.
    """
    if not schema_name:
        raise ValueError("schema_name is required for ulid_primary_key_column")
    return Column(
        name,
        ulid_domain_type(schema_name),
        primary_key=True,
        nullable=False,
    )
