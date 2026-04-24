"""Configuration tests for SeaweedFS substrate settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from resources.substrates.seaweedfs.config import SeaweedFSSubstrateSettings

_CREDS = {"access_key_id": "test-key", "secret_access_key": "test-secret"}


def _settings(**kwargs) -> SeaweedFSSubstrateSettings:
    return SeaweedFSSubstrateSettings(**{**_CREDS, **kwargs})


def test_default_extension_normalizes_dot_prefix() -> None:
    """Default extension should normalize and strip optional dot prefix."""
    settings = _settings(default_extension=".DAT")

    assert settings.default_extension == "dat"


def test_endpoint_url_normalizes_trailing_slash() -> None:
    """Endpoint URL should be stored without trailing slashes."""
    settings = _settings(endpoint_url="http://seaweedfs:8333/")

    assert settings.endpoint_url == "http://seaweedfs:8333"


def test_bucket_is_required() -> None:
    """Blank bucket should fail validation."""
    with pytest.raises(ValueError, match="bucket is required"):
        _settings(bucket="  ")


def test_credentials_are_required() -> None:
    """Missing access_key_id or secret_access_key should fail validation."""
    with pytest.raises(ValidationError):
        SeaweedFSSubstrateSettings(secret_access_key="x")
    with pytest.raises(ValidationError):
        SeaweedFSSubstrateSettings(access_key_id="x")
