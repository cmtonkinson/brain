"""Unit tests for the Python skill adapter."""

import sys
from pathlib import Path

import pytest

from skills.adapters.python_adapter import PythonSkillAdapter
from skills.context import SkillContext
from skills.registry import SkillRuntimeEntry
from skills.registry_schema import (
    AutonomyLevel,
    CallTargetKind,
    CallTargetRef,
    Entrypoint,
    EntrypointRuntime,
    LogicSkillDefinition,
    SkillKind,
    SkillStatus,
)
from skills.errors import SkillExecutionError


def _make_skill(module: str, handler: str) -> SkillRuntimeEntry:
    """Build a SkillRuntimeEntry for Python adapter tests."""
    definition = LogicSkillDefinition(
        name="demo_skill",
        version="1.0.0",
        status=SkillStatus.enabled,
        description="Demo",
        kind=SkillKind.logic,
        inputs_schema={"type": "object"},
        outputs_schema={"type": "object"},
        capabilities=["obsidian.read"],
        side_effects=[],
        autonomy=AutonomyLevel.L1,
        entrypoint=Entrypoint(runtime=EntrypointRuntime.python, module=module, handler=handler),
        call_targets=[CallTargetRef(kind=CallTargetKind.op, name="dummy_op", version="1.0.0")],
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


def _write_module(tmp_path: Path, name: str, body: str) -> None:
    """Write a temporary Python module to disk for adapter tests."""
    module_path = tmp_path / f"{name}.py"
    module_path.write_text(body, encoding="utf-8")
    sys.path.insert(0, str(tmp_path))


@pytest.mark.asyncio
async def test_python_adapter_runs_sync_handler(tmp_path):
    """Ensure the adapter runs synchronous handlers."""
    _write_module(
        tmp_path,
        "sync_skill",
        """
        def run(inputs, context):
            return {"echo": inputs["value"]}
        """.strip(),
    )
    skill = _make_skill("sync_skill", "run")
    adapter = PythonSkillAdapter()

    result = await adapter.execute(skill, {"value": "ok"}, SkillContext({"obsidian.read"}))

    assert result["echo"] == "ok"


@pytest.mark.asyncio
async def test_python_adapter_runs_async_handler(tmp_path):
    """Ensure the adapter runs async handlers."""
    _write_module(
        tmp_path,
        "async_skill",
        """
        async def run(inputs, context):
            return {"echo": inputs["value"]}
        """.strip(),
    )
    skill = _make_skill("async_skill", "run")
    adapter = PythonSkillAdapter()

    result = await adapter.execute(skill, {"value": "ok"}, SkillContext({"obsidian.read"}))

    assert result["echo"] == "ok"


@pytest.mark.asyncio
async def test_python_adapter_invalid_handler(tmp_path):
    """Ensure invalid handlers raise a SkillExecutionError."""
    _write_module(
        tmp_path,
        "bad_skill",
        """
        def run(inputs, context):
            return {"ok": True}
        """.strip(),
    )
    skill = _make_skill("bad_skill", "missing")
    adapter = PythonSkillAdapter()

    with pytest.raises(SkillExecutionError):
        await adapter.execute(skill, {}, SkillContext({"obsidian.read"}))


@pytest.mark.asyncio
async def test_python_adapter_passes_invoker(tmp_path):
    """Ensure the adapter passes the invoker when the handler accepts it."""
    _write_module(
        tmp_path,
        "invoker_skill",
        """
        def run(inputs, context, invoker):
            return {"has_invoker": invoker is not None}
        """.strip(),
    )
    skill = _make_skill("invoker_skill", "run")
    adapter = PythonSkillAdapter()

    result = await adapter.execute(
        skill,
        {"value": "ok"},
        SkillContext({"obsidian.read"}),
        invoker={"ok": True},
    )

    assert result["has_invoker"] is True
