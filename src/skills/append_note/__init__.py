"""Skill: append to a note."""

from __future__ import annotations

from typing import Any

from skills.services import get_services


async def run(inputs: dict[str, Any], context) -> dict[str, Any]:
    obsidian = get_services().obsidian
    if obsidian is None:
        raise RuntimeError("Obsidian service not available")

    path = inputs["path"]
    content = inputs["content"]
    result = await obsidian.append_to_note(path, content)
    return {"path": result.get("path", path)}
