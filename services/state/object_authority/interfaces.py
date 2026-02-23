"""Transport-neutral protocol interfaces used by Object Authority Service."""

from __future__ import annotations

from typing import Protocol

from services.state.object_authority.domain import ObjectRecord


class ObjectRepository(Protocol):
    """Protocol for authoritative object metadata persistence operations."""

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
        """Create one object record when missing and return the current record."""

    def get_object_by_key(self, *, object_key: str) -> ObjectRecord | None:
        """Read one object record by canonical key."""

    def delete_object_by_key(self, *, object_key: str) -> bool:
        """Delete one object record by canonical key and return existed flag."""
