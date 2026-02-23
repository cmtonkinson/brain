"""Authoritative Postgres repository for Object Authority Service state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from packages.brain_shared.ids import generate_ulid_bytes
from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
from services.state.object_authority.domain import (
    ObjectMetadata,
    ObjectRecord,
    ObjectRef,
)
from services.state.object_authority.interfaces import ObjectRepository

from .schema import objects


class PostgresObjectRepository(ObjectRepository):
    """SQL repository over OAS-owned schema tables."""

    def __init__(self, sessions: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions

    def upsert_object(
        self,
        *,
        object_key: str,
        digest_algorithm: str,
        digest_version: str,
        digest_hex: str,
        extension: str,
        content_type: str,
        size_bytes: int,
        original_filename: str,
        source_uri: str,
    ) -> ObjectRecord:
        """Ensure one unique object row exists for digest identity."""
        with self._sessions.session() as session:
            stmt = insert(objects).values(
                id=generate_ulid_bytes(),
                object_key=object_key,
                digest_algorithm=digest_algorithm,
                digest_version=digest_version,
                digest_hex=digest_hex,
                extension=extension,
                content_type=content_type,
                size_bytes=size_bytes,
                original_filename=original_filename,
                source_uri=source_uri,
            )
            stmt = stmt.on_conflict_do_nothing(constraint="uq_objects_digest_identity")
            session.execute(stmt)

            row = (
                session.execute(
                    select(objects).where(
                        objects.c.digest_version == digest_version,
                        objects.c.digest_algorithm == digest_algorithm,
                        objects.c.digest_hex == digest_hex,
                    )
                )
                .mappings()
                .one()
            )
            return _to_object(row)

    def get_object_by_key(self, *, object_key: str) -> ObjectRecord | None:
        """Read one object row by object key."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(objects).where(objects.c.object_key == object_key)
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_object(row)

    def delete_object_by_key(self, *, object_key: str) -> bool:
        """Delete one object row by key and return whether row existed."""
        with self._sessions.session() as session:
            result = session.execute(
                delete(objects).where(objects.c.object_key == object_key)
            )
            return int(result.rowcount or 0) > 0


def _to_object(row: dict[str, Any]) -> ObjectRecord:
    """Map one SQL row to strict domain object record."""
    return ObjectRecord(
        ref=ObjectRef(object_key=str(row["object_key"])),
        metadata=ObjectMetadata(
            digest_algorithm=str(row["digest_algorithm"]),
            digest_version=str(row["digest_version"]),
            digest_hex=str(row["digest_hex"]),
            extension=str(row["extension"]),
            content_type=str(row["content_type"]),
            size_bytes=int(row["size_bytes"]),
            original_filename=str(row["original_filename"]),
            source_uri=str(row["source_uri"]),
            created_at=_row_dt(row, "created_at"),
            updated_at=_row_dt(row, "updated_at"),
        ),
    )


def _row_dt(row: dict[str, Any], column: str) -> datetime:
    """Read and normalize one timezone-aware datetime field from SQL row."""
    value = row.get(column)
    if not isinstance(value, datetime):
        raise ValueError(f"expected datetime column for {column}")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
