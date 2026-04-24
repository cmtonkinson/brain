"""Tests for the mcp-status slash command op."""

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
                pending_tool_count=1,
            ),
            SimpleNamespace(
                system_id="money-tree",
                kind="mcp",
                ready=False,
                tool_count=0,
                pending_tool_count=0,
            ),
        )

    def describe_ops(self):
        return (
            SimpleNamespace(op_id="eventkit--list-reminders", kind="mcp"),
            SimpleNamespace(
                op_id="eventkit--list-calendar-events",
                kind="mcp",
            ),
            SimpleNamespace(op_id="vault-get-file", kind="native"),
        )

    def list_dynamic_op_classifications(self):
        return (
            SimpleNamespace(
                op_id="eventkit--create-event",
                source_kind="mcp",
                effect=None,
                approval=None,
            ),
            SimpleNamespace(
                op_id="eventkit--list-reminders",
                source_kind="mcp",
                effect="read",
                approval="never",
            ),
        )


def test_execute_lists_mcp_servers(monkeypatch: Any) -> None:
    """No input should list configured MCP servers with active and pending counts."""
    module = _load_execute()
    monkeypatch.setattr(module, "BrainSdkClient", _FakeClient)

    result = module.execute({})

    assert "eventkit" in result
    assert "(available) 2 tools active, 1 unclassified" in result
    assert "money-tree" in result
    assert "(offline)" in result
    assert "/op-classify" in result


def test_execute_lists_servers_without_pending_hint_when_all_classified(
    monkeypatch: Any,
) -> None:
    """When no server has unclassified tools the hint footer is omitted."""
    module = _load_execute()

    class _AllClassified(_FakeClient):
        def list_tool_system_hints(self):
            return (
                SimpleNamespace(
                    system_id="eventkit",
                    kind="mcp",
                    ready=True,
                    tool_count=3,
                    pending_tool_count=0,
                ),
            )

    monkeypatch.setattr(module, "BrainSdkClient", _AllClassified)

    result = module.execute({})

    assert "(available) 3 tools active, 0 unclassified" in result
    assert "/op-classify" not in result


def test_execute_lists_tools_for_named_server(monkeypatch: Any) -> None:
    """Server input should list active and unclassified MCP Ops separately."""
    module = _load_execute()
    monkeypatch.setattr(module, "BrainSdkClient", _FakeClient)

    result = module.execute({"server_id": "eventkit"})

    lines = result.splitlines()
    assert lines[0] == "Status: (available)"
    assert "2 Active Tools:" in result
    assert "eventkit--list-calendar-events" in result
    assert "eventkit--list-reminders" in result
    assert "1 Unclassified Tools:" in result
    assert "eventkit--create-event" in result
    assert "/op-classify" in result
