"""Behavior tests for Object Authority Service authority semantics."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from packages.brain_shared.envelope import EnvelopeKind, new_meta
from services.state.object_authority.config import ObjectAuthoritySettings
from services.state.object_authority.domain import (
    ObjectMetadata,
    ObjectRecord,
    ObjectRef,
)
from services.state.object_authority.implementation import (
    DefaultObjectAuthorityService,
)


@dataclass
class _BlobWriteCall:
    digest_hex: str
    extension: str
    content: bytes


class _FakeBlobStore:
    """In-memory filesystem adapter fake for OAS behavior tests."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], bytes] = {}
        self.write_calls: list[_BlobWriteCall] = []
        self.raise_on_write: Exception | None = None

    def write_blob(self, *, digest_hex: str, extension: str, content: bytes) -> None:
        self.write_calls.append(
            _BlobWriteCall(digest_hex=digest_hex, extension=extension, content=content)
        )
        if self.raise_on_write is not None:
            raise self.raise_on_write
        self.rows[(digest_hex, extension)] = content

    def read_blob(self, *, digest_hex: str, extension: str) -> bytes:
        return self.rows[(digest_hex, extension)]

    def stat_blob(self, *, digest_hex: str, extension: str) -> object:
        del digest_hex, extension
        return object()

    def delete_blob(self, *, digest_hex: str, extension: str) -> bool:
        return self.rows.pop((digest_hex, extension), None) is not None


class _FakeRepository:
    """In-memory metadata repository fake for OAS behavior tests."""

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


def _meta() -> object:
    """Return valid envelope metadata for OAS test requests."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def _service() -> tuple[DefaultObjectAuthorityService, _FakeRepository, _FakeBlobStore]:
    """Build deterministic OAS service with in-memory dependencies."""
    repo = _FakeRepository()
    blob = _FakeBlobStore()
    service = DefaultObjectAuthorityService(
        settings=ObjectAuthoritySettings(),
        repository=repo,
        blob_store=blob,
        default_extension="blob",
    )
    return service, repo, blob


def _expected_digest(content: bytes) -> str:
    """Return expected seeded digest for prototype key semantics."""
    return hashlib.sha256(b"b1:\0" + content).hexdigest()


def test_put_get_stat_delete_happy_path() -> None:
    """OAS should provide full blob lifecycle semantics."""
    service, _repo, _blob = _service()

    put = service.put_object(
        meta=_meta(),
        content=b"hello",
        extension="ext",
        content_type="text/plain",
        original_filename="hello.txt",
        source_uri="file:///hello.txt",
    )
    assert put.ok is True
    assert put.payload is not None
    object_key = put.payload.value.ref.object_key

    stat = service.stat_object(meta=_meta(), object_key=object_key)
    assert stat.ok is True
    assert stat.payload is not None
    assert stat.payload.value.metadata.extension == "ext"

    get = service.get_object(meta=_meta(), object_key=object_key)
    assert get.ok is True
    assert get.payload is not None
    assert get.payload.value.content == b"hello"

    deleted = service.delete_object(meta=_meta(), object_key=object_key)
    assert deleted.ok is True
    assert deleted.payload is not None
    assert deleted.payload.value is True


def test_put_preserves_digest_key_semantics_and_extension_as_metadata() -> None:
    """Duplicate content with different extension should resolve to same key."""
    service, _repo, blob = _service()

    first = service.put_object(
        meta=_meta(),
        content=b"abc",
        extension="txt",
        content_type="text/plain",
        original_filename="a.txt",
        source_uri="",
    )
    second = service.put_object(
        meta=_meta(),
        content=b"abc",
        extension="bin",
        content_type="application/octet-stream",
        original_filename="a.bin",
        source_uri="",
    )

    assert first.ok is True
    assert second.ok is True
    assert first.payload is not None
    assert second.payload is not None
    assert first.payload.value.ref.object_key == second.payload.value.ref.object_key
    assert first.payload.value.metadata.extension == "txt"
    assert second.payload.value.metadata.extension == "txt"
    assert first.payload.value.ref.object_key == f"b1:sha256:{_expected_digest(b'abc')}"
    assert [call.extension for call in blob.write_calls] == ["txt", "txt"]


def test_get_and_stat_return_not_found_for_missing_object() -> None:
    """Missing objects must map to not-found domain errors."""
    service, _repo, _blob = _service()

    get = service.get_object(
        meta=_meta(),
        object_key=f"b1:sha256:{'a' * 64}",
    )
    stat = service.stat_object(
        meta=_meta(),
        object_key=f"b1:sha256:{'b' * 64}",
    )

    assert get.ok is False
    assert stat.ok is False
    assert get.errors[0].category.value == "not_found"
    assert stat.errors[0].category.value == "not_found"


def test_delete_is_idempotent_for_missing_object() -> None:
    """Delete should return true even when object does not exist."""
    service, _repo, _blob = _service()

    response = service.delete_object(meta=_meta(), object_key=f"b1:sha256:{'c' * 64}")

    assert response.ok is True
    assert response.payload is not None
    assert response.payload.value is True


def test_put_uses_default_extension_when_blank() -> None:
    """Blank extension should fall back to configured default extension."""
    service, _repo, _blob = _service()

    result = service.put_object(
        meta=_meta(),
        content=b"abc",
        extension="",
        content_type="",
        original_filename="",
        source_uri="",
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.metadata.extension == "blob"


def test_put_maps_filesystem_errors_to_dependency() -> None:
    """Filesystem write failures should map to dependency-category errors."""
    service, _repo, blob = _service()
    blob.raise_on_write = RuntimeError("disk full")

    result = service.put_object(
        meta=_meta(),
        content=b"abc",
        extension="bin",
        content_type="",
        original_filename="",
        source_uri="",
    )

    assert result.ok is False
    assert result.errors[0].category.value == "dependency"


def test_put_rejects_content_larger_than_configured_max() -> None:
    """Content larger than configured max size should fail validation."""
    repo = _FakeRepository()
    blob = _FakeBlobStore()
    service = DefaultObjectAuthorityService(
        settings=ObjectAuthoritySettings(max_blob_size_bytes=2),
        repository=repo,
        blob_store=blob,
        default_extension="blob",
    )

    result = service.put_object(
        meta=_meta(),
        content=b"abc",
        extension="bin",
        content_type="",
        original_filename="",
        source_uri="",
    )

    assert result.ok is False
    assert result.errors[0].category.value == "validation"


def test_put_cleans_blob_when_metadata_upsert_fails() -> None:
    """Blob should be cleaned when metadata write fails after blob persistence."""
    service, repo, blob = _service()
    repo.raise_on_upsert = RuntimeError("db unavailable")

    result = service.put_object(
        meta=_meta(),
        content=b"abc",
        extension="bin",
        content_type="",
        original_filename="",
        source_uri="",
    )

    digest = _expected_digest(b"abc")
    assert result.ok is False
    assert result.errors[0].category.value == "dependency"
    assert (digest, "bin") not in blob.rows
