import pytest

from skills.adapters.mcp_adapter import MCPSkillAdapter
from skills.context import SkillContext
from skills.registry import SkillRuntimeEntry
from skills.registry_schema import AutonomyLevel, Entrypoint, EntrypointRuntime, SkillDefinition, SkillStatus
from skills.errors import SkillExecutionError

pytest.skip("MCP skill adapter deprecated in v2; replaced by op runtime.", allow_module_level=True)


class DummyCodeMode:
    """Minimal code mode stub for MCP adapter tests."""

    def __init__(self):
        """Initialize the stub with a call log."""
        self.called = []

    async def call_tool_chain(self, code, confirm_destructive=False, timeout=None):
        """Record tool calls and return a synthetic response."""
        self.called.append(code)
        return {"ok": True, "code": code}


def _make_skill(tool: str | None) -> SkillRuntimeEntry:
    """Build a SkillRuntimeEntry for MCP adapter tests."""
    definition = SkillDefinition(
        name="mcp_skill",
        version="1.0.0",
        status=SkillStatus.enabled,
        description="MCP",
        inputs_schema={"type": "object"},
        outputs_schema={"type": "object"},
        capabilities=["filesystem.read"],
        side_effects=[],
        autonomy=AutonomyLevel.L1,
        entrypoint=Entrypoint(runtime=EntrypointRuntime.mcp, tool=tool),
        failure_modes=[
            {
                "code": "skill_unexpected_error",
                "description": "Unexpected skill failure.",
                "retryable": False,
            }
        ],
    )
    return SkillRuntimeEntry(
        definition=definition,
        status=SkillStatus.enabled,
        autonomy=AutonomyLevel.L1,
        rate_limit=None,
        channels=None,
        actors=None,
    )


@pytest.mark.asyncio
async def test_mcp_adapter_calls_tool():
    """Ensure the MCP adapter executes the configured tool."""
    code_mode = DummyCodeMode()
    adapter = MCPSkillAdapter(code_mode)
    skill = _make_skill("filesystem.read")
    context = SkillContext({"filesystem.read"})

    result = await adapter.execute(skill, {"path": "/tmp"}, context)

    assert result["result"]["ok"] is True
    assert code_mode.called


@pytest.mark.asyncio
async def test_mcp_adapter_requires_tool_name():
    """Ensure missing tool names cause execution errors."""
    code_mode = DummyCodeMode()
    adapter = MCPSkillAdapter(code_mode)
    skill = _make_skill("filesystem.read")
    skill.definition.entrypoint.tool = None
    context = SkillContext({"filesystem.read"})

    with pytest.raises(SkillExecutionError):
        await adapter.execute(skill, {}, context)


@pytest.mark.asyncio
async def test_mcp_adapter_checks_capabilities():
    """Ensure the adapter rejects missing capability contexts."""
    code_mode = DummyCodeMode()
    adapter = MCPSkillAdapter(code_mode)
    skill = _make_skill("filesystem.read")
    context = SkillContext(set())

    with pytest.raises(SkillExecutionError):
        await adapter.execute(skill, {}, context)
