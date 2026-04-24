"""Real-provider integration tests for SeaweedFS S3-compatible substrate."""

from __future__ import annotations

import hashlib

import pytest

from resources.substrates.seaweedfs import (
    SeaweedFSBlobSubstrate,
    SeaweedFSSubstrateSettings,
)
from tests.integration.helpers import real_provider_tests_enabled

pytest_plugins = ("tests.integration.fixtures",)

pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)

_TEST_BUCKET = "brain-int-test"


def _substrate(endpoint: str) -> SeaweedFSBlobSubstrate:
    settings = SeaweedFSSubstrateSettings(
        endpoint_url=endpoint,
        bucket=_TEST_BUCKET,
        access_key_id="test",
        secret_access_key="test",
    )
    return SeaweedFSBlobSubstrate(settings=settings)


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_write_read_stat_delete_roundtrip(
    seaweedfs_endpoint: str,
) -> None:
    """Substrate should write, read, stat, and delete a blob."""
    substrate = _substrate(seaweedfs_endpoint)
    content = b"integration test blob content"
    digest = _digest(content)

    key = substrate.write_blob(
        digest_hex=digest,
        extension="txt",
        content=content,
    )
    assert key
    assert digest in key

    read_back = substrate.read_blob(
        digest_hex=digest,
        extension="txt",
    )
    assert read_back == content

    stat = substrate.stat_blob(
        digest_hex=digest,
        extension="txt",
    )
    assert stat.key == key
    assert stat.size_bytes == len(content)

    deleted = substrate.delete_blob(
        digest_hex=digest,
        extension="txt",
    )
    assert deleted is True

    with pytest.raises(FileNotFoundError):
        substrate.read_blob(digest_hex=digest, extension="txt")


def test_write_is_idempotent(
    seaweedfs_endpoint: str,
) -> None:
    """Writing the same digest twice should not fail or duplicate."""
    substrate = _substrate(seaweedfs_endpoint)
    content = b"idempotent blob"
    digest = _digest(content)

    key1 = substrate.write_blob(digest_hex=digest, extension="blob", content=content)
    key2 = substrate.write_blob(digest_hex=digest, extension="blob", content=content)
    assert key1 == key2

    substrate.delete_blob(digest_hex=digest, extension="blob")


def test_delete_nonexistent_returns_false(
    seaweedfs_endpoint: str,
) -> None:
    """Deleting a key that does not exist should return False."""
    substrate = _substrate(seaweedfs_endpoint)
    digest = _digest(b"does not exist")

    result = substrate.delete_blob(digest_hex=digest, extension="blob")
    assert result is False


def test_health_probe(
    seaweedfs_endpoint: str,
) -> None:
    """Health probe should report ready against live SeaweedFS."""
    substrate = _substrate(seaweedfs_endpoint)
    status = substrate.health()
    assert status.ready is True
