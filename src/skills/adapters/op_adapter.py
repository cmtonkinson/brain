"""Adapters for executing native and MCP ops."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
from typing import Any

from services.code_mode import CodeModeManager

from ..context import SkillContext
from ..registry import OpRuntimeEntry
from ..op_runtime import OpExecutionError


class NativeOpAdapter:
    """Adapter for locally implemented native ops."""

    def __init__(self, timeout_seconds: int = 30) -> None:
        """Initialize the adapter with a timeout."""
        self._timeout_seconds = timeout_seconds

    async def execute(
        self,
        op_entry: OpRuntimeEntry,
        inputs: dict[str, Any],
        context: SkillContext,
    ) -> dict[str, Any]:
        """Execute a native op handler with timeout protection."""
        module_name = op_entry.definition.module
        handler_name = op_entry.definition.handler
        if not module_name or not handler_name:
            raise OpExecutionError(
                "invalid_op_entrypoint",
                "Native op requires module and handler.",
            )

        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise OpExecutionError(
                "op_module_import_failed",
                f"Failed to import module {module_name}: {exc}",
            ) from exc

        handler = getattr(module, handler_name, None)
        if handler is None:
            raise OpExecutionError(
                "op_handler_missing",
                f"Handler {handler_name} not found in {module_name}.",
            )

        async def _call_handler() -> dict[str, Any]:
            if inspect.iscoroutinefunction(handler):
                return await handler(inputs, context)
            return await asyncio.to_thread(handler, inputs, context)

        try:
            return await asyncio.wait_for(_call_handler(), timeout=self._timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise OpExecutionError("op_timeout", "Op execution timed out.") from exc
        except OpExecutionError:
            raise
        except Exception as exc:
            raise OpExecutionError(
                "op_execution_failed",
                f"Native op failed: {exc}",
            ) from exc


class MCPOpAdapter:
    """Adapter for MCP-backed ops."""

    def __init__(self, code_mode: CodeModeManager, timeout_seconds: int = 30) -> None:
        """Initialize the adapter with a Code-Mode manager and timeout."""
        self._code_mode = code_mode
        self._timeout_seconds = timeout_seconds

    async def execute(
        self,
        op_entry: OpRuntimeEntry,
        inputs: dict[str, Any],
        context: SkillContext,
    ) -> dict[str, Any]:
        """Execute an MCP op by calling the configured tool."""
        tool_name = op_entry.definition.tool
        if not tool_name:
            raise OpExecutionError(
                "invalid_op_entrypoint",
                "MCP op requires tool name.",
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
            raise OpExecutionError(
                "op_tool_call_failed",
                f"MCP op call failed: {exc}",
            ) from exc

        return {"result": response}
