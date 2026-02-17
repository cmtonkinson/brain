"""Letta tool: fetch a note from Obsidian Local REST."""

from __future__ import annotations

import httpx

from config import settings
from services.http_client import HttpClient


def read_note(path: str, max_chars: int = 12000) -> str:
    """Read a note from Obsidian by path.

    Args:
        path: Vault-relative path to the note.
        max_chars: Maximum characters to return.
    """

    base_url = settings.obsidian.url
    api_key = settings.obsidian.api_key
    if not api_key:
        raise ValueError("OBSIDIAN_API_KEY is not configured.")

    headers = {"Authorization": f"Bearer {api_key}"}
    client = HttpClient()
    try:
        response = client.get(f"{base_url.rstrip('/')}/vault/{path}", headers=headers)
        content = response.text
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n... (note truncated)"
        return content
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Note not found: {path}"
        raise
