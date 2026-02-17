"""Skill: create a note."""

from __future__ import annotations

from typing import Any

from skills.composition import SkillInvocation
from skills.context import SkillContext


async def run(
    inputs: dict[str, Any],
    context: SkillContext,
    invoker: SkillInvocation | None = None,
) -> dict[str, Any]:
    """Create a note via the governed op invocation interface."""
    if invoker is None:
        raise RuntimeError("Skill invocation interface not available")
    path = inputs["path"]
    content = inputs["content"]
    result = await invoker.invoke_op(
        "obsidian_create_note",
        {"path": path, "content": content},
        version="1.0.0",
    )
    return result.output
