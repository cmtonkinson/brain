"""Skill: search notes."""

from __future__ import annotations

from typing import Any

from skills.services import get_services


async def run(inputs: dict[str, Any], context) -> dict[str, Any]:
    obsidian = get_services().obsidian
    if obsidian is None:
        raise RuntimeError("Obsidian service not available")

    query = inputs["query"]
    limit = inputs.get("limit", 10)
    results = await obsidian.search(query, limit=limit)

    formatted = []
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
