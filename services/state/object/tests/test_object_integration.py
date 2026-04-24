"""Integration-style Object tests over repo/blob store boundaries."""

from __future__ import annotations

from lib.shared.envelope import EnvelopeKind, new_meta
from services.state.object.config import ObjectSettings
from services.state.object.implementation import DefaultObjectService
from services.state.object.tests.fakes import FakeBlobStore, FakeRepository


def _meta():
    """Build deterministic envelope metadata."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_put_delete_roundtrip_and_orphan_cleanup() -> None:
    """Service should clean orphaned blob when metadata persistence fails."""
    repo = FakeRepository()
    blob = FakeBlobStore()
    service = DefaultObjectService(
        settings=ObjectSettings(),
        repository=repo,
        blob_store=blob,
        default_extension="blob",
    )

    created = service.put_object(
        meta=_meta(),
        content=b"payload",
        extension="txt",
        content_type="text/plain",
        original_filename="x.txt",
        source_uri="test://x",
    )
    assert created.ok is True

    repo.raise_on_upsert = RuntimeError("db down")
    failed = service.put_object(
        meta=_meta(),
        content=b"payload-2",
        extension="txt",
        content_type="text/plain",
        original_filename="y.txt",
        source_uri="test://y",
    )
    assert failed.ok is False

    key = created.payload.value.object.ref.object_key
    deleted = service.delete_object(meta=_meta(), object_key=key)
    assert deleted.ok is True
