"""Unit tests for Code-Mode manager behaviors."""

from __future__ import annotations

import pytest

from services.code_mode import CodeModeManager


class DummyTool:
    """Simple tool stub with name and description."""

    def __init__(self, name: str, description: str) -> None:
        """Initialize with a name and description."""
        self.name = name
        self.description = description


class DummyClient:
    """Code-Mode client stub returning a fixed response."""

    def __init__(self) -> None:
        """Initialize call tracking."""
        self.called = False

    async def call_tool_chain(self, code: str, timeout: int | None = None) -> dict[str, object]:
        """Return a canned response and record the call."""
        self.called = True
        return {"logs": ["log-entry"], "result": "ok"}


def test_route_namespace_detects_targets() -> None:
    """_route_namespace maps queries to known namespaces."""
    manager = CodeModeManager(client=None, config_path=None, timeout=1)

    assert manager._route_namespace("read file") == "filesystem"
    assert manager._route_namespace("calendar reminder") == "eventkit"
    assert manager._route_namespace("github pull request") == "github"
    assert manager._route_namespace("something else") is None


def test_rank_tools_orders_by_score() -> None:
    """_rank_tools prefers name matches over description matches."""
    manager = CodeModeManager(client=None, config_path=None, timeout=1)
    tools = [
        DummyTool("filesystem.read_file", "reads a file"),
        DummyTool("filesystem.list_dir", "list files"),
    ]

    ranked = manager._rank_tools(tools, query="read")

    assert ranked[0].name == "filesystem.read_file"


@pytest.mark.asyncio
async def test_call_tool_chain_blocks_destructive() -> None:
    """call_tool_chain blocks destructive operations without confirmation."""
    manager = CodeModeManager(client=DummyClient(), config_path=None, timeout=1)

    response = await manager.call_tool_chain(
        "tools.files.delete('/tmp/foo')", confirm_destructive=False
    )

    assert "Potentially destructive operations detected" in response
    assert manager.client.called is False


@pytest.mark.asyncio
async def test_call_tool_chain_renders_logs_and_result() -> None:
    """call_tool_chain returns logs and result output."""
    manager = CodeModeManager(client=DummyClient(), config_path=None, timeout=1)

    response = await manager.call_tool_chain(
        "tools.files.read('/tmp/foo')", confirm_destructive=True
    )

    assert "Logs:" in response
    assert "log-entry" in response
    assert "Result: ok" in response
