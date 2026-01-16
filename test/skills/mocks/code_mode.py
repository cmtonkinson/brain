"""Mock Code-Mode manager for skill tests."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MockCodeModeManager:
    responses: dict[str, object] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    raise_on_call: bool = False

    async def call_tool_chain(self, code: str, confirm_destructive: bool = False, timeout: int | None = None) -> object:
        self.calls.append(code)
        if self.raise_on_call:
            raise RuntimeError("mock tool failure")
        return self.responses.get(code, {"result": None})

    async def search_tools(self, query: str) -> str:
        return "mocked"
