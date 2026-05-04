"""Unit tests for the per-executor command-shaping registry."""

from __future__ import annotations

import pytest

from resources.adapters.coding.adapter import ExecutorId
from resources.adapters.coding.registry import UnknownExecutorError, shape_command


class TestShapeCommand:
    """shape_command() returns CLI argv per executor."""

    def test_claude_code_print_flag(self) -> None:
        argv = shape_command(
            executor=ExecutorId.CLAUDE_CODE, cli="claude", prompt="do thing"
        )
        assert argv == ("claude", "-p", "do thing")

    def test_codex_uses_exec_subcommand(self) -> None:
        argv = shape_command(executor=ExecutorId.CODEX, cli="codex", prompt="do thing")
        assert argv == ("codex", "exec", "do thing")

    def test_opencode_uses_run_subcommand(self) -> None:
        argv = shape_command(
            executor=ExecutorId.OPENCODE, cli="opencode", prompt="do thing"
        )
        assert argv == ("opencode", "run", "do thing")

    def test_uses_configured_cli_name(self) -> None:
        argv = shape_command(
            executor=ExecutorId.CLAUDE_CODE,
            cli="claude-code-binary",
            prompt="x",
        )
        assert argv[0] == "claude-code-binary"

    def test_unknown_raises(self) -> None:
        class _Sentinel:
            value = "unknown"

        with pytest.raises(UnknownExecutorError):
            shape_command(executor=_Sentinel(), cli="x", prompt="y")  # type: ignore[arg-type]
