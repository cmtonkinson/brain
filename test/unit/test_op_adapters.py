"""Unit tests for op adapter execution paths."""

import sys
from pathlib import Path

import pytest

from skills.adapters.op_adapter import MCPOpAdapter, NativeOpAdapter
from skills.context import SkillContext
from skills.registry import OpRuntimeEntry
from skills.registry_schema import AutonomyLevel, OpDefinition, OpRuntime, SkillStatus
from skills.op_runtime import OpExecutionError


class DummyCodeMode:
    """Minimal code mode stub for MCP op adapter tests."""

    def __init__(self):
        """Initialize the stub with a call log."""
        self.called = []

    async def call_tool_chain(self, code, confirm_destructive=False, timeout=None):
        """Record tool calls and return a synthetic response."""
        self.called.append(code)
        return {"ok": True, "code": code}


def _make_op_entry(runtime: OpRuntime, module: str | None, handler: str | None, tool: str | None) -> OpRuntimeEntry:
    """Build an OpRuntimeEntry for adapter tests."""
    definition = OpDefinition(
        name="demo_op",
        version="1.0.0",
        status=SkillStatus.enabled,
        description="Demo",
        inputs_schema={"type": "object"},
        outputs_schema={"type": "object"},
        capabilities=["obsidian.read"],
        side_effects=[],
        autonomy=AutonomyLevel.L1,
        runtime=runtime,
        module=module,
        handler=handler,
        tool=tool,
        failure_modes=[
            {
                "code": "op_unexpected_error",
                "description": "Unexpected op failure.",
                "retryable": False,
            }
        ],
    )
    return OpRuntimeEntry(
        definition=definition,
        status=SkillStatus.enabled,
        autonomy=AutonomyLevel.L1,
        rate_limit=None,
        channels=None,
        actors=None,
    )


def _write_module(tmp_path: Path, name: str, body: str) -> None:
    """Write a temporary Python module to disk for adapter tests."""
    module_path = tmp_path / f"{name}.py"
    module_path.write_text(body, encoding="utf-8")
    sys.path.insert(0, str(tmp_path))


@pytest.mark.asyncio
async def test_native_op_adapter_runs_handler(tmp_path):
    """Ensure the native op adapter runs handlers."""
    _write_module(
        tmp_path,
        "native_op",
        """
        def run(inputs, context):
            return {"echo": inputs["value"]}
        """.strip(),
    )
    op_entry = _make_op_entry(OpRuntime.native, "native_op", "run", None)
    adapter = NativeOpAdapter()

    result = await adapter.execute(op_entry, {"value": "ok"}, SkillContext({"obsidian.read"}))

    assert result["echo"] == "ok"


@pytest.mark.asyncio
async def test_native_op_adapter_missing_handler(tmp_path):
    """Ensure missing handlers raise execution errors."""
    _write_module(
        tmp_path,
        "native_bad",
        """
        def run(inputs, context):
            return {"ok": True}
        """.strip(),
    )
    op_entry = _make_op_entry(OpRuntime.native, "native_bad", "missing", None)
    adapter = NativeOpAdapter()

    with pytest.raises(OpExecutionError):
        await adapter.execute(op_entry, {}, SkillContext({"obsidian.read"}))


@pytest.mark.asyncio
async def test_mcp_op_adapter_calls_tool():
    """Ensure the MCP op adapter executes the configured tool."""
    code_mode = DummyCodeMode()
    adapter = MCPOpAdapter(code_mode)
    op_entry = _make_op_entry(OpRuntime.mcp, None, None, "filesystem.read")
    context = SkillContext({"obsidian.read"})

    result = await adapter.execute(op_entry, {"path": "/tmp"}, context)

    assert result["result"]["ok"] is True
    assert code_mode.called
