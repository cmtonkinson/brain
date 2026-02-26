"""Configuration tests for filesystem substrate settings."""

from __future__ import annotations

from resources.substrates.filesystem.config import FilesystemSubstrateSettings


def test_default_extension_normalizes_dot_prefix() -> None:
    """Default extension should normalize and strip optional dot prefix."""
    settings = FilesystemSubstrateSettings(default_extension=".DAT")

    assert settings.default_extension == "dat"


def test_root_dir_is_required() -> None:
    """Blank root directory should fail validation."""
    try:
        FilesystemSubstrateSettings(root_dir="  ")
    except ValueError as exc:
        assert "root_dir is required" in str(exc)
    else:
        raise AssertionError("expected validation error")
