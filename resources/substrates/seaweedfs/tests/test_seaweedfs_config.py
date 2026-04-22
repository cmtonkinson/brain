"""Configuration tests for SeaweedFS substrate settings."""

from __future__ import annotations

from resources.substrates.seaweedfs.config import SeaweedFSSubstrateSettings


def test_default_extension_normalizes_dot_prefix() -> None:
    """Default extension should normalize and strip optional dot prefix."""
    settings = SeaweedFSSubstrateSettings(default_extension=".DAT")

    assert settings.default_extension == "dat"


def test_endpoint_url_normalizes_trailing_slash() -> None:
    """Endpoint URL should be stored without trailing slashes."""
    settings = SeaweedFSSubstrateSettings(endpoint_url="http://seaweedfs:8333/")

    assert settings.endpoint_url == "http://seaweedfs:8333"


def test_bucket_is_required() -> None:
    """Blank bucket should fail validation."""
    try:
        SeaweedFSSubstrateSettings(bucket="  ")
    except ValueError as exc:
        assert "bucket is required" in str(exc)
    else:
        raise AssertionError("expected validation error")
