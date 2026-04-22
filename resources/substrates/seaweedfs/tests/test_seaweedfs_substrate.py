"""Unit tests for SeaweedFS blob substrate behavior."""

from __future__ import annotations

import httpx
import pytest

from resources.substrates.seaweedfs import (
    SeaweedFSBlobSubstrate,
    SeaweedFSSubstrateSettings,
)

_DIGEST = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"


def _substrate(handler) -> SeaweedFSBlobSubstrate:
    """Create one SeaweedFS substrate with a mock HTTP transport."""
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return SeaweedFSBlobSubstrate(settings=SeaweedFSSubstrateSettings(), client=client)


def test_resolve_key_uses_digest_fanout_and_extension() -> None:
    """Provider key layout should shard by digest prefix and include extension."""
    substrate = SeaweedFSBlobSubstrate(settings=SeaweedFSSubstrateSettings())

    key = substrate.resolve_key(digest_hex=_DIGEST, extension="ext")

    assert key == f"objects/ab/cd/{_DIGEST}.ext"


def test_write_read_stat_delete_cycle() -> None:
    """Write, read, stat, and delete should use path-style S3 object URLs."""
    objects: dict[str, bytes] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "HEAD" and path == "/brain-oas":
            return httpx.Response(200)
        if request.method == "HEAD":
            content = objects.get(path)
            if content is None:
                return httpx.Response(404)
            return httpx.Response(
                200,
                headers={
                    "content-length": str(len(content)),
                    "etag": '"abc123"',
                    "content-type": "application/octet-stream",
                },
            )
        if request.method == "PUT":
            objects[path] = request.content
            return httpx.Response(200)
        if request.method == "GET":
            content = objects.get(path)
            if content is None:
                return httpx.Response(404)
            return httpx.Response(200, content=content)
        if request.method == "DELETE":
            objects.pop(path, None)
            return httpx.Response(204)
        raise AssertionError(request.method)

    substrate = _substrate(_handler)
    key = f"objects/ab/cd/{_DIGEST}.bin"
    path = f"/brain-oas/{key}"

    assert substrate.health().ready is True
    assert substrate.write_blob(digest_hex=_DIGEST, extension="bin", content=b"hello")
    assert objects[path] == b"hello"
    assert substrate.read_blob(digest_hex=_DIGEST, extension="bin") == b"hello"
    stat = substrate.stat_blob(digest_hex=_DIGEST, extension="bin")
    assert stat.key == key
    assert stat.size_bytes == 5
    assert stat.etag == "abc123"
    assert substrate.delete_blob(digest_hex=_DIGEST, extension="bin") is True
    assert substrate.delete_blob(digest_hex=_DIGEST, extension="bin") is False


def test_write_is_idempotent_when_object_exists() -> None:
    """Second write to an existing object key should be no-op success."""
    calls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(200)
        if request.method == "PUT":
            raise AssertionError("PUT should not be called")
        raise AssertionError(request.method)

    substrate = _substrate(_handler)

    key = substrate.write_blob(digest_hex=_DIGEST, extension="bin", content=b"same")

    assert key == f"objects/ab/cd/{_DIGEST}.bin"
    assert calls == ["HEAD"]


def test_read_missing_object_raises_file_not_found() -> None:
    """Missing SeaweedFS objects should map to FileNotFoundError."""
    substrate = _substrate(lambda _request: httpx.Response(404))

    with pytest.raises(FileNotFoundError):
        substrate.read_blob(digest_hex=_DIGEST, extension="bin")


def test_health_reports_provider_probe_failure() -> None:
    """Unsuccessful bucket probes should return unhealthy status."""
    substrate = _substrate(lambda _request: httpx.Response(503))

    status = substrate.health()

    assert status.ready is False
    assert "503" in status.detail


def test_invalid_digest_hex_is_rejected() -> None:
    """Digest must be lowercase hex with exact sha256 length."""
    settings = SeaweedFSSubstrateSettings()
    substrate = SeaweedFSBlobSubstrate(settings=settings)

    with pytest.raises(ValueError, match="exactly 64 hex characters"):
        substrate.resolve_key(digest_hex="abc123", extension="bin")

    with pytest.raises(ValueError, match="must be hexadecimal"):
        substrate.resolve_key(digest_hex="g" * 64, extension="bin")
