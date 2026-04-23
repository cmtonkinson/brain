"""Tests for the mcp-status slash command capability."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _load_execute() -> Any:
    path = Path(__file__).resolve().parents[1] / "execute.py"
    spec = importlib.util.spec_from_file_location("mcp_status_execute", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeClient:
    def __init__(self, *, source: str, principal: str) -> None:
        del source, principal

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def list_tool_system_hints(self):
        return (
            SimpleNamespace(
                system_id="eventkit",
                kind="mcp",
                ready=True,
                tool_count=2,
            ),
            SimpleNamespace(
                system_id="money-tree",
                kind="mcp",
                ready=False,
                tool_count=0,
            ),
        )

    def describe_capabilities(self):
        return (
            SimpleNamespace(capability_id="eventkit--list-reminders", kind="mcp_op"),
            SimpleNamespace(
                capability_id="eventkit--list-calendar-events",
                kind="mcp_op",
            ),
            SimpleNamespace(capability_id="vault-get-file", kind="native_op"),
        )


def test_execute_lists_mcp_servers(monkeypatch: Any) -> None:
    """No input should list configured MCP servers with status."""
    module = _load_execute()
    monkeypatch.setattr(module, "BrainSdkClient", _FakeClient)

    result = module.execute({})

    assert "eventkit" in result
    assert "available, 2 tools" in result
    assert "money-tree" in result
    assert "offline" in result


def test_execute_lists_tools_for_named_server(monkeypatch: Any) -> None:
    """Server input should list MCP Ops for that server."""
    module = _load_execute()
    monkeypatch.setattr(module, "BrainSdkClient", _FakeClient)

    result = module.execute({"server_id": "eventkit"})

    assert result.splitlines()[0] == "Status: available"
    assert "2 Tools:" in result
    assert "eventkit--list-calendar-events" in result
    assert "eventkit--list-reminders" in result
