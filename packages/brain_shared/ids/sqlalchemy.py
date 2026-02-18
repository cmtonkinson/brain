"""SQLAlchemy helpers for ULID-backed primary keys."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column
from sqlalchemy.dialects.postgresql import BYTEA


ULID_BYTES_LENGTH = 16


def ulid_primary_key_column(
    name: str = "id",
    *,
    length_constraint_name: str | None = None,
) -> Column[bytes]:
    """Return a standard ULID primary-key column definition.

    Uses PostgreSQL BYTEA with a strict 16-byte check constraint to represent
    canonical 128-bit ULIDs generated in application code.
    """
    constraint = ulid_length_check(
        name,
        length_constraint_name or f"ck_{name}_ulid_16",
    )
    return Column(name, BYTEA, constraint, primary_key=True, nullable=False)


def ulid_length_check(column_name: str, constraint_name: str) -> CheckConstraint:
    """Return a CHECK constraint enforcing fixed 16-byte ULID storage."""
    return CheckConstraint(
        f"octet_length({column_name}) = {ULID_BYTES_LENGTH}",
        name=constraint_name,
    )
