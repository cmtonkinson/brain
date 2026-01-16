"""Adapter for local Python skills."""

from __future__ import annotations

import asyncio
import importlib
import inspect
from typing import Any

from ..context import SkillContext
from ..registry import SkillRuntimeEntry
from ..runtime import SkillExecutionError


class PythonSkillAdapter:
    def __init__(self, timeout_seconds: int = 30) -> None:
        self._timeout_seconds = timeout_seconds

    async def execute(
        self,
        skill: SkillRuntimeEntry,
        inputs: dict[str, Any],
        context: SkillContext,
    ) -> dict[str, Any]:
        entrypoint = skill.definition.entrypoint
        module_name = entrypoint.module
        handler_name = entrypoint.handler
        if not module_name or not handler_name:
            raise SkillExecutionError(
                "invalid_entrypoint",
                "Python entrypoint requires module and handler.",
            )

        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise SkillExecutionError(
                "module_import_failed",
                f"Failed to import module {module_name}: {exc}",
            ) from exc

        handler = getattr(module, handler_name, None)
        if handler is None:
            raise SkillExecutionError(
                "handler_missing",
                f"Handler {handler_name} not found in {module_name}.",
            )

        async def _call_handler() -> dict[str, Any]:
            if inspect.iscoroutinefunction(handler):
                return await handler(inputs, context)
            return await asyncio.to_thread(handler, inputs, context)

        try:
            return await asyncio.wait_for(_call_handler(), timeout=self._timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise SkillExecutionError("timeout", "Skill execution timed out.") from exc
        except SkillExecutionError:
            raise
        except Exception as exc:
            raise SkillExecutionError(
                "execution_failed",
                f"Python skill failed: {exc}",
            ) from exc
