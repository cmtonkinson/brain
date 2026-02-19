"""SQLAlchemy helpers for ULID-backed primary keys."""

from __future__ import annotations

from sqlalchemy import Column
from sqlalchemy.dialects import postgresql


ULID_BYTES_LENGTH = 16


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
    domain_type = postgresql.DOMAIN(
        name="ulid_bin",
        data_type=postgresql.BYTEA(),
        schema=schema_name,
        create_type=False,
    )
    return Column(name, domain_type, primary_key=True, nullable=False)
