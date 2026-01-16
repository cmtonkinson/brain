"""Adapter for MCP/UTCP-backed skills."""

from __future__ import annotations

import json
from typing import Any

from services.code_mode import CodeModeManager

from ..context import SkillContext
from ..registry import SkillRuntimeEntry
from ..errors import SkillExecutionError


class MCPSkillAdapter:
    def __init__(self, code_mode: CodeModeManager, timeout_seconds: int = 30) -> None:
        self._code_mode = code_mode
        self._timeout_seconds = timeout_seconds

    async def execute(
        self,
        skill: SkillRuntimeEntry,
        inputs: dict[str, Any],
        context: SkillContext,
    ) -> dict[str, Any]:
        entrypoint = skill.definition.entrypoint
        tool_name = entrypoint.tool
        if not tool_name:
            raise SkillExecutionError(
                "invalid_entrypoint",
                "MCP entrypoint requires tool name.",
            )

        missing = [
            cap for cap in skill.definition.capabilities if cap not in context.allowed_capabilities
        ]
        if missing:
            raise SkillExecutionError(
                "capability_missing",
                "Context missing required capabilities.",
                {"missing": missing},
            )

        payload = json.dumps(inputs, separators=(",", ":"))
        code = f"tools.{tool_name}({payload})"

        try:
            response = await self._code_mode.call_tool_chain(
                code,
                confirm_destructive=False,
                timeout=self._timeout_seconds,
            )
        except Exception as exc:
            raise SkillExecutionError(
                "tool_call_failed",
                f"MCP tool call failed: {exc}",
            ) from exc

        return {"result": response}
