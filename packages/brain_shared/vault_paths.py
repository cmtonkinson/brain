"""Shared vault path normalization helpers for VAS and Obsidian adapter."""

from __future__ import annotations


def normalize_vault_relative_path(value: str, *, allow_root: bool) -> str:
    """Normalize and validate one vault-relative path string."""
    path = value.strip().replace("\\", "/")
    if path == "":
        if allow_root:
            return ""
        raise ValueError("path must be non-empty")
    if path.startswith("/"):
        raise ValueError("path must be vault-relative")

    parts = path.split("/")
    normalized_parts: list[str] = []
    for part in parts:
        if part in {"", ".", ".."}:
            raise ValueError("path contains invalid segment")
        normalized_parts.append(part)
    return "/".join(normalized_parts)


def normalize_vault_directory_path(value: str, *, allow_root: bool = False) -> str:
    """Normalize one vault directory path, preserving empty root when allowed."""
    normalized = normalize_vault_relative_path(value, allow_root=allow_root)
    return normalized.rstrip("/")


def normalize_vault_file_path(value: str, *, suffix: str = ".md") -> str:
    """Normalize one vault file path and enforce a required suffix."""
    normalized = normalize_vault_relative_path(value, allow_root=False)
    if not normalized.lower().endswith(suffix.lower()):
        raise ValueError(f"file path must end with {suffix}")
    return normalized
