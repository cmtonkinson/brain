"""Skill composition API for nested invocation."""

from __future__ import annotations

from typing import Any

from .context import SkillContext
from .runtime import SkillRuntime, ExecutionResult


class SkillComposer:
    def __init__(self, runtime: SkillRuntime) -> None:
        self._runtime = runtime

    async def invoke(
        self,
        parent_context: SkillContext,
        name: str,
        inputs: dict[str, Any],
        version: str | None = None,
    ) -> ExecutionResult:
        skill = self._runtime._registry.get_skill(name, version)
        child_context = parent_context.child(skill.definition.capabilities)
        return await self._runtime.execute(name, inputs, child_context, version=version)
