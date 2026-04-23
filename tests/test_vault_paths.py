"""Unit tests for shared vault path normalization helpers."""

from __future__ import annotations

import pytest

from lib.shared.vault_paths import normalize_vault_directory_path


def test_normalize_vault_directory_path_strips_trailing_slash() -> None:
    """Directory normalization should accept a trailing slash."""
    assert normalize_vault_directory_path("professional/") == "professional"


def test_normalize_vault_directory_path_rejects_invalid_segment() -> None:
    """Directory normalization should still reject unsafe path segments."""
    with pytest.raises(ValueError, match="invalid segment"):
        normalize_vault_directory_path("professional//drafts")
