"""Skill: search notes."""

from __future__ import annotations

from typing import Any

from skills.composition import SkillInvocation
from skills.context import SkillContext


async def run(
    inputs: dict[str, Any],
    context: SkillContext,
    invoker: SkillInvocation | None = None,
) -> dict[str, Any]:
    """Search notes via the governed op invocation interface."""
    if invoker is None:
        raise RuntimeError("Skill invocation interface not available")
    query = inputs["query"]
    limit = inputs.get("limit", 10)
    result = await invoker.invoke_op(
        "obsidian_search",
        {"query": query, "limit": limit},
        version="1.0.0",
    )
    return result.output
