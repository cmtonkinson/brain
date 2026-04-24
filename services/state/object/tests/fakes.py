"""Shared test fakes for Object Service unit and integration tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from resources.substrates.seaweedfs import BlobHealthStatus
from services.state.object.domain import (
    ObjectMetadata,
    ObjectRecord,
    ObjectRef,
)


@dataclass
class _BlobWriteCall:
    digest_hex: str
    extension: str
    content: bytes


class FakeBlobStore:
    """In-memory blob substrate fake for Object behavior tests."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], bytes] = {}
        self.write_calls: list[_BlobWriteCall] = []
        self.raise_on_write: Exception | None = None

    def health(self) -> BlobHealthStatus:
        """Return ready fake substrate health."""
        return BlobHealthStatus(ready=True, detail="ok")

    def write_blob(self, *, digest_hex: str, extension: str, content: bytes) -> None:
        self.write_calls.append(
            _BlobWriteCall(digest_hex=digest_hex, extension=extension, content=content)
        )
        if self.raise_on_write is not None:
            raise self.raise_on_write
        self.rows[(digest_hex, extension)] = content

    def read_blob(self, *, digest_hex: str, extension: str) -> bytes:
        key = (digest_hex, extension)
        if key not in self.rows:
            raise FileNotFoundError(f"{digest_hex}.{extension}")
        return self.rows[key]

    def delete_blob(self, *, digest_hex: str, extension: str) -> bool:
        return self.rows.pop((digest_hex, extension), None) is not None


class FakeRepository:
    """In-memory metadata repository fake for Object behavior tests."""

    def __init__(self) -> None:
        self.rows_by_key: dict[str, ObjectRecord] = {}
        self.rows_by_digest: dict[tuple[str, str, str], str] = {}
        self.raise_on_upsert: Exception | None = None

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
        if self.raise_on_upsert is not None:
            raise self.raise_on_upsert

        digest_key = (digest_version, digest_algorithm, digest_hex)
        existing_key = self.rows_by_digest.get(digest_key)
        if existing_key is not None:
            return self.rows_by_key[existing_key]

        now = datetime.now(tz=UTC)
        row = ObjectRecord(
            ref=ObjectRef(object_key=object_key),
            metadata=ObjectMetadata(
                digest_algorithm=digest_algorithm,
                digest_version=digest_version,
                digest_hex=digest_hex,
                extension=extension,
                content_type=content_type,
                size_bytes=size_bytes,
                original_filename=original_filename,
                source_uri=source_uri,
                created_at=now,
                updated_at=now,
            ),
        )
        self.rows_by_key[object_key] = row
        self.rows_by_digest[digest_key] = object_key
        return row

    def get_object_by_key(self, *, object_key: str) -> ObjectRecord | None:
        return self.rows_by_key.get(object_key)

    def delete_object_by_key(self, *, object_key: str) -> bool:
        row = self.rows_by_key.pop(object_key, None)
        if row is None:
            return False
        digest_key = (
            row.metadata.digest_version,
            row.metadata.digest_algorithm,
            row.metadata.digest_hex,
        )
        self.rows_by_digest.pop(digest_key, None)
        return True
