"""Unit tests for SeaweedFS blob substrate behavior."""

from __future__ import annotations

import hashlib
import hmac

import httpx
import pytest

from resources.substrates.seaweedfs import (
    SeaweedFSBlobSubstrate,
    SeaweedFSSubstrateSettings,
)
from resources.substrates.seaweedfs.seaweedfs_substrate import (
    _canonical_uri,
    _sign,
    _signing_key,
)

_DIGEST = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
_CREDS = {"access_key_id": "test-key", "secret_access_key": "test-secret"}


def _settings(**kwargs) -> SeaweedFSSubstrateSettings:
    return SeaweedFSSubstrateSettings(**{**_CREDS, **kwargs})


def _substrate(handler) -> SeaweedFSBlobSubstrate:
    """Create one SeaweedFS substrate with a mock HTTP transport."""
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return SeaweedFSBlobSubstrate(settings=_settings(), client=client)


def test_resolve_key_uses_digest_fanout_and_extension() -> None:
    """Provider key layout should shard by digest prefix and include extension."""
    substrate = SeaweedFSBlobSubstrate(settings=_settings())

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
            if path in objects:
                objects.pop(path)
                return httpx.Response(204)
            return httpx.Response(404)
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


def test_delete_missing_object_returns_false_without_delete_call() -> None:
    """Delete should probe existence first so missing objects return False."""
    calls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(404)
        if request.method == "DELETE":
            raise AssertionError("DELETE should not be called")
        raise AssertionError(request.method)

    substrate = _substrate(_handler)

    assert substrate.delete_blob(digest_hex=_DIGEST, extension="bin") is False
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
    substrate = SeaweedFSBlobSubstrate(settings=_settings())

    with pytest.raises(ValueError, match="exactly 64 hex characters"):
        substrate.resolve_key(digest_hex="abc123", extension="bin")

    with pytest.raises(ValueError, match="must be hexadecimal"):
        substrate.resolve_key(digest_hex="g" * 64, extension="bin")


def test_canonical_uri_encodes_special_characters() -> None:
    """Canonical URI must percent-encode spaces and non-ASCII path chars."""
    assert (
        _canonical_uri("http://host/bucket/path with spaces")
        == "/bucket/path%20with%20spaces"
    )
    assert _canonical_uri("http://host/bucket/caf\u00e9") == "/bucket/caf%C3%A9"
    assert _canonical_uri("http://host/bucket/a/b") == "/bucket/a/b"
    assert _canonical_uri("http://host/") == "/"


def test_canonical_uri_preserves_tildes_and_slashes() -> None:
    """Tildes and slashes must not be percent-encoded in canonical URIs."""
    assert _canonical_uri("http://host/~user/path") == "/~user/path"


def test_sign_produces_hmac_sha256() -> None:
    """_sign must return the correct HMAC-SHA256 digest for known inputs."""
    expected = hmac.new(b"key", b"message", hashlib.sha256).digest()
    assert _sign(b"key", "message") == expected


def test_signing_key_derives_correct_key() -> None:
    """_signing_key must chain four HMAC rounds per the SigV4 spec."""
    secret = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
    date = "20130524"
    region = "us-east-1"

    date_key = _sign(f"AWS4{secret}".encode(), date)
    region_key = _sign(date_key, region)
    service_key = _sign(region_key, "s3")
    expected = _sign(service_key, "aws4_request")

    assert (
        _signing_key(secret_access_key=secret, datestamp=date, region=region)
        == expected
    )
