"""Letta tool: fetch a note from Obsidian Local REST."""

from __future__ import annotations

import os

import httpx


def read_note(path: str, max_chars: int = 12000) -> str:
    """Read a note from Obsidian by path.

    Args:
        path: Vault-relative path to the note.
        max_chars: Maximum characters to return.
    """
    base_url = os.environ.get("OBSIDIAN_URL", "http://host.docker.internal:27123")
    api_key = os.environ.get("OBSIDIAN_API_KEY")
    if not api_key:
        raise ValueError("OBSIDIAN_API_KEY is not configured.")

    headers = {"Authorization": f"Bearer {api_key}"}
    response = httpx.get(
        f"{base_url.rstrip('/')}/vault/{path}",
        headers=headers,
        timeout=30.0,
    )
    if response.status_code == 404:
        return f"Note not found: {path}"
    response.raise_for_status()
    content = response.text
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n... (note truncated)"
    return content
