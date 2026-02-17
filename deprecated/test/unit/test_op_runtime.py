"""Unit tests for op runtime behavior."""

import json
from pathlib import Path

import pytest

from skills.context import SkillContext
from skills.op_runtime import OpPolicyError, OpRuntime, OpValidationError
from skills.policy import DefaultPolicy
from skills.registry import OpRegistryLoader


class DummyAdapter:
    """Simple adapter that returns a fixed output."""

    def __init__(self, output):
        """Initialize the adapter with a static output."""
        self._output = output

    async def execute(self, op_entry, inputs, context):
        """Return the static output for any invocation."""
        return self._output


def _write_json(path: Path, data: dict) -> None:
    """Serialize JSON test data to disk."""
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _setup_registry(
    tmp_path: Path,
    outputs_schema: dict,
    *,
    inputs_schema: dict | None = None,
    status: str = "enabled",
    autonomy: str = "L1",
) -> OpRegistryLoader:
    """Create a temporary op registry for runtime validation tests."""
    registry_path = tmp_path / "op-registry.json"
    capabilities_path = tmp_path / "capabilities.json"

    _write_json(
        capabilities_path,
        {
            "version": "1.0.0",
            "capabilities": [
                {"id": "obsidian.read", "description": "", "group": "memory", "status": "active"},
            ],
        },
    )

    _write_json(
        registry_path,
        {
            "registry_version": "1.0.0",
            "ops": [
                {
                    "name": "obsidian_search",
                    "version": "1.0.0",
                    "status": status,
                    "description": "Search",
                    "inputs_schema": inputs_schema
                    or {
                        "type": "object",
                        "required": ["query"],
                        "properties": {"query": {"type": "string"}},
                    },
                    "outputs_schema": outputs_schema,
                    "capabilities": ["obsidian.read"],
                    "side_effects": [],
                    "autonomy": autonomy,
                    "runtime": "native",
                    "module": "json",
                    "handler": "dumps",
                    "failure_modes": [
                        {
                            "code": "op_unexpected_error",
                            "description": "Unexpected op failure.",
                            "retryable": False,
                        }
                    ],
                }
            ],
        },
    )

    loader = OpRegistryLoader(
        base_path=registry_path,
        overlay_paths=[],
        capability_path=capabilities_path,
    )
    loader.load()
    return loader


@pytest.mark.asyncio
async def test_op_runtime_validates_inputs(tmp_path):
    """Ensure input schema validation rejects missing fields."""
    loader = _setup_registry(
        tmp_path,
        {"type": "object", "required": ["results"], "properties": {"results": {"type": "array"}}},
    )
    runtime = OpRuntime(
        registry=loader,
        policy=DefaultPolicy(),
        adapters={"native": DummyAdapter({"results": []})},
    )
    context = SkillContext(
        allowed_capabilities={"obsidian.read"},
        actor="user",
        channel="cli",
    )

    with pytest.raises(OpValidationError):
        await runtime.execute("obsidian_search", {}, context)


@pytest.mark.asyncio
async def test_op_runtime_executes_successfully(tmp_path):
    """Ensure enabled ops execute and return outputs."""
    loader = _setup_registry(
        tmp_path,
        {"type": "object", "required": ["results"], "properties": {"results": {"type": "array"}}},
    )
    runtime = OpRuntime(
        registry=loader,
        policy=DefaultPolicy(),
        adapters={"native": DummyAdapter({"results": []})},
    )
    context = SkillContext(
        allowed_capabilities={"obsidian.read"},
        confirmed=True,
        actor="user",
        channel="cli",
    )

    result = await runtime.execute("obsidian_search", {"query": "hi"}, context)

    assert result.output == {"results": []}


@pytest.mark.asyncio
async def test_op_runtime_validates_outputs(tmp_path):
    """Ensure output schema validation rejects invalid types."""
    loader = _setup_registry(
        tmp_path,
        {"type": "object", "required": ["results"], "properties": {"results": {"type": "array"}}},
    )
    runtime = OpRuntime(
        registry=loader,
        policy=DefaultPolicy(),
        adapters={"native": DummyAdapter({"results": "oops"})},
    )
    context = SkillContext(
        allowed_capabilities={"obsidian.read"},
        confirmed=True,
        actor="user",
        channel="cli",
    )

    with pytest.raises(OpValidationError):
        await runtime.execute("obsidian_search", {"query": "hi"}, context)


@pytest.mark.asyncio
async def test_op_runtime_denies_policy(tmp_path):
    """Ensure policy enforcement denies missing capabilities."""
    loader = _setup_registry(
        tmp_path,
        {"type": "object", "required": ["results"], "properties": {"results": {"type": "array"}}},
    )
    runtime = OpRuntime(
        registry=loader,
        policy=DefaultPolicy(),
        adapters={"native": DummyAdapter({"results": []})},
    )
    context = SkillContext(
        allowed_capabilities=set(),
        actor="user",
        channel="cli",
    )

    with pytest.raises(OpPolicyError):
        await runtime.execute("obsidian_search", {"query": "hi"}, context)


@pytest.mark.asyncio
async def test_op_runtime_denies_disabled_op(tmp_path):
    """Ensure disabled ops cannot execute."""
    loader = _setup_registry(
        tmp_path,
        {"type": "object", "required": ["results"], "properties": {"results": {"type": "array"}}},
        status="disabled",
    )
    runtime = OpRuntime(
        registry=loader,
        policy=DefaultPolicy(),
        adapters={"native": DummyAdapter({"results": []})},
    )
    context = SkillContext(
        allowed_capabilities={"obsidian.read"},
        actor="user",
        channel="cli",
    )

    with pytest.raises(OpPolicyError):
        await runtime.execute("obsidian_search", {"query": "hi"}, context)
