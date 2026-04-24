"""Unit tests for shared vault path normalization helpers."""

from __future__ import annotations

import pytest

from lib.shared.vault_paths import (
    normalize_vault_directory_path,
    normalize_vault_file_path,
    normalize_vault_relative_path,
)


# ---------------------------------------------------------------------------
# normalize_vault_relative_path
# ---------------------------------------------------------------------------


def test_normalize_vault_relative_path_accepts_simple_path() -> None:
    """Simple vault-relative path should pass through unchanged."""
    assert (
        normalize_vault_relative_path("notes/hello.md", allow_root=False)
        == "notes/hello.md"
    )


def test_normalize_vault_relative_path_strips_whitespace() -> None:
    """Leading and trailing whitespace should be stripped."""
    assert (
        normalize_vault_relative_path("  notes/hello.md  ", allow_root=False)
        == "notes/hello.md"
    )


def test_normalize_vault_relative_path_converts_backslashes() -> None:
    """Backslashes should be converted to forward slashes."""
    assert (
        normalize_vault_relative_path("notes\\hello.md", allow_root=False)
        == "notes/hello.md"
    )


def test_normalize_vault_relative_path_rejects_absolute_path() -> None:
    """Absolute paths should be rejected."""
    with pytest.raises(ValueError, match="vault-relative"):
        normalize_vault_relative_path("/notes/hello.md", allow_root=False)


def test_normalize_vault_relative_path_rejects_empty_when_root_disallowed() -> None:
    """Empty path with allow_root=False should raise ValueError."""
    with pytest.raises(ValueError, match="non-empty"):
        normalize_vault_relative_path("", allow_root=False)


def test_normalize_vault_relative_path_allows_empty_when_root_allowed() -> None:
    """Empty path with allow_root=True should return empty string."""
    assert normalize_vault_relative_path("", allow_root=True) == ""


@pytest.mark.parametrize(
    "path",
    ["a//b", "a/./b", "a/../b", "./a", "../a"],
)
def test_normalize_vault_relative_path_rejects_invalid_segments(path: str) -> None:
    """Dot, dotdot, and empty segments should be rejected."""
    with pytest.raises(ValueError, match="invalid segment"):
        normalize_vault_relative_path(path, allow_root=False)


# ---------------------------------------------------------------------------
# normalize_vault_directory_path
# ---------------------------------------------------------------------------


def test_normalize_vault_directory_path_strips_trailing_slash() -> None:
    """Directory normalization should accept a trailing slash."""
    assert normalize_vault_directory_path("professional/") == "professional"


def test_normalize_vault_directory_path_rejects_invalid_segment() -> None:
    """Directory normalization should still reject unsafe path segments."""
    with pytest.raises(ValueError, match="invalid segment"):
        normalize_vault_directory_path("professional//drafts")


def test_normalize_vault_directory_path_rejects_root_slash() -> None:
    """Root slash should be rejected when allow_root is False (default)."""
    with pytest.raises(ValueError, match="vault-relative"):
        normalize_vault_directory_path("/")


def test_normalize_vault_directory_path_allows_root_when_configured() -> None:
    """Empty string with allow_root=True should return empty root."""
    assert normalize_vault_directory_path("", allow_root=True) == ""


# ---------------------------------------------------------------------------
# normalize_vault_file_path
# ---------------------------------------------------------------------------


def test_normalize_vault_file_path_accepts_md_suffix() -> None:
    """Markdown files should pass validation."""
    assert normalize_vault_file_path("notes/hello.md") == "notes/hello.md"


def test_normalize_vault_file_path_rejects_wrong_suffix() -> None:
    """Non-markdown files should be rejected by default."""
    with pytest.raises(ValueError, match="must end with .md"):
        normalize_vault_file_path("notes/hello.txt")


def test_normalize_vault_file_path_accepts_custom_suffix() -> None:
    """Custom suffix parameter should override the default .md check."""
    assert (
        normalize_vault_file_path("data/export.csv", suffix=".csv") == "data/export.csv"
    )


def test_normalize_vault_file_path_suffix_check_is_case_insensitive() -> None:
    """Suffix comparison should be case-insensitive."""
    assert normalize_vault_file_path("NOTES/HELLO.MD") == "NOTES/HELLO.MD"
