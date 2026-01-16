"""Native ops for interacting with the Obsidian vault."""

from __future__ import annotations

from typing import Any

from skills.context import SkillContext
from skills.services import get_services


async def search(inputs: dict[str, Any], context: SkillContext) -> dict[str, Any]:
    """Search the Obsidian vault and return formatted results."""
    obsidian = get_services().obsidian
    if obsidian is None:
        raise RuntimeError("Obsidian service not available")

    query = inputs["query"]
    limit = inputs.get("limit", 10)
    results = await obsidian.search(query, limit=limit)

    formatted: list[str] = []
    for result in results:
        if isinstance(result, dict):
            path = result.get("path") or result.get("filename") or "Unknown"
            matches = result.get("matches", [])
            snippet = ""
            if matches:
                first = matches[0]
                if isinstance(first, dict):
                    snippet = first.get("match") or first.get("context") or ""
                else:
                    snippet = str(first)
            formatted.append(f"{path}: {snippet}".strip())
        else:
            formatted.append(str(result))

    return {"results": formatted}


async def read_note(inputs: dict[str, Any], context: SkillContext) -> dict[str, Any]:
    """Read a note from the Obsidian vault."""
    obsidian = get_services().obsidian
    if obsidian is None:
        raise RuntimeError("Obsidian service not available")

    path = inputs["path"]
    content = await obsidian.get_note(path)
    return {"content": content}


async def create_note(inputs: dict[str, Any], context: SkillContext) -> dict[str, Any]:
    """Create a new note in the Obsidian vault."""
    obsidian = get_services().obsidian
    if obsidian is None:
        raise RuntimeError("Obsidian service not available")

    path = inputs["path"]
    content = inputs["content"]
    result = await obsidian.create_note(path, content)
    return {"path": result.get("path", path)}


async def append_note(inputs: dict[str, Any], context: SkillContext) -> dict[str, Any]:
    """Append content to an existing Obsidian note."""
    obsidian = get_services().obsidian
    if obsidian is None:
        raise RuntimeError("Obsidian service not available")

    path = inputs["path"]
    content = inputs["content"]
    result = await obsidian.append_to_note(path, content)
    return {"path": result.get("path", path)}
