"""Unit tests for skill composition behavior."""

import json
from pathlib import Path

import pytest

from skills.composition import SkillComposer
from skills.context import SkillContext
from skills.errors import SkillPolicyError, SkillRuntimeError
from skills.policy import DefaultPolicy
from skills.registry import SkillRegistryLoader
from skills.runtime import SkillRuntime


class DummyAdapter:
    """Adapter stub for composition tests."""

    async def execute(self, skill, inputs, context, invoker=None):
        """Return a fixed response for test invocations."""
        return {"ok": True}


def _write_json(path: Path, data: dict) -> None:
    """Serialize JSON test data to disk."""
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest.mark.asyncio
async def test_child_skill_inherits_capability_limits(tmp_path):
    """Ensure child skills cannot exceed parent capability scopes."""
    registry_path = tmp_path / "skill-registry.json"
    op_registry_path = tmp_path / "op-registry.json"
    capabilities_path = tmp_path / "capabilities.json"

    _write_json(
        capabilities_path,
        {
            "version": "1.0.0",
            "capabilities": [
                {"id": "obsidian.read", "description": "", "group": "memory", "status": "active"},
                {"id": "obsidian.write", "description": "", "group": "memory", "status": "active"},
            ],
        },
    )

    _write_json(
        registry_path,
        {
            "registry_version": "1.0.0",
            "skills": [
                {
                    "name": "parent_skill",
                    "version": "1.0.0",
                    "status": "enabled",
                    "description": "Parent",
                    "kind": "logic",
                    "inputs_schema": {"type": "object"},
                    "outputs_schema": {"type": "object"},
                    "capabilities": ["obsidian.read"],
                    "side_effects": [],
                    "autonomy": "L1",
                    "entrypoint": {"runtime": "python", "module": "x", "handler": "run"},
                    "call_targets": [{"kind": "skill", "name": "writer", "version": "1.0.0"}],
                    "failure_modes": [
                        {
                            "code": "skill_unexpected_error",
                            "description": "Unexpected skill failure.",
                            "retryable": False,
                        }
                    ],
                },
                {
                    "name": "writer",
                    "version": "1.0.0",
                    "status": "enabled",
                    "description": "Write",
                    "kind": "logic",
                    "inputs_schema": {"type": "object"},
                    "outputs_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
                    "capabilities": ["obsidian.write"],
                    "side_effects": ["obsidian.write"],
                    "autonomy": "L1",
                    "entrypoint": {"runtime": "python", "module": "x", "handler": "run"},
                    "call_targets": [{"kind": "op", "name": "dummy_op", "version": "1.0.0"}],
                    "failure_modes": [
                        {
                            "code": "skill_unexpected_error",
                            "description": "Unexpected skill failure.",
                            "retryable": False,
                        }
                    ],
                },
            ],
        },
    )
    _write_json(
        op_registry_path,
        {
            "registry_version": "1.0.0",
            "ops": [
                {
                    "name": "dummy_op",
                    "version": "1.0.0",
                    "status": "enabled",
                    "description": "Dummy op",
                    "inputs_schema": {"type": "object"},
                    "outputs_schema": {"type": "object"},
                    "capabilities": ["obsidian.write"],
                    "side_effects": [],
                    "autonomy": "L1",
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

    registry = SkillRegistryLoader(
        base_path=registry_path,
        overlay_paths=[],
        capability_path=capabilities_path,
        op_registry_path=op_registry_path,
    )
    registry.load()
    runtime = SkillRuntime(
        registry=registry,
        policy=DefaultPolicy(),
        adapters={"python": DummyAdapter()},
    )
    composer = SkillComposer(runtime)

    parent_context = SkillContext({"obsidian.read"})
    parent_skill = registry.get_skill("parent_skill")

    with pytest.raises(SkillPolicyError):
        await composer.invoke(parent_skill, parent_context, "writer", {})


@pytest.mark.asyncio
async def test_composer_rejects_undeclared_targets(tmp_path):
    """Ensure undeclared call targets fail fast."""
    registry_path = tmp_path / "skill-registry.json"
    op_registry_path = tmp_path / "op-registry.json"
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
            "skills": [
                {
                    "name": "parent_skill",
                    "version": "1.0.0",
                    "status": "enabled",
                    "description": "Parent",
                    "kind": "logic",
                    "inputs_schema": {"type": "object"},
                    "outputs_schema": {"type": "object"},
                    "capabilities": ["obsidian.read"],
                    "side_effects": [],
                    "autonomy": "L1",
                    "entrypoint": {"runtime": "python", "module": "x", "handler": "run"},
                    "call_targets": [{"kind": "skill", "name": "other", "version": "1.0.0"}],
                    "failure_modes": [
                        {
                            "code": "skill_unexpected_error",
                            "description": "Unexpected skill failure.",
                            "retryable": False,
                        }
                    ],
                },
                {
                    "name": "other",
                    "version": "1.0.0",
                    "status": "enabled",
                    "description": "Other",
                    "kind": "logic",
                    "inputs_schema": {"type": "object"},
                    "outputs_schema": {"type": "object"},
                    "capabilities": ["obsidian.read"],
                    "side_effects": [],
                    "autonomy": "L1",
                    "entrypoint": {"runtime": "python", "module": "x", "handler": "run"},
                    "call_targets": [{"kind": "op", "name": "dummy_op", "version": "1.0.0"}],
                    "failure_modes": [
                        {
                            "code": "skill_unexpected_error",
                            "description": "Unexpected skill failure.",
                            "retryable": False,
                        }
                    ],
                },
                {
                    "name": "writer",
                    "version": "1.0.0",
                    "status": "enabled",
                    "description": "Write",
                    "kind": "logic",
                    "inputs_schema": {"type": "object"},
                    "outputs_schema": {"type": "object"},
                    "capabilities": ["obsidian.read"],
                    "side_effects": [],
                    "autonomy": "L1",
                    "entrypoint": {"runtime": "python", "module": "x", "handler": "run"},
                    "call_targets": [{"kind": "op", "name": "dummy_op", "version": "1.0.0"}],
                    "failure_modes": [
                        {
                            "code": "skill_unexpected_error",
                            "description": "Unexpected skill failure.",
                            "retryable": False,
                        }
                    ],
                },
            ],
        },
    )
    _write_json(
        op_registry_path,
        {
            "registry_version": "1.0.0",
            "ops": [
                {
                    "name": "dummy_op",
                    "version": "1.0.0",
                    "status": "enabled",
                    "description": "Dummy op",
                    "inputs_schema": {"type": "object"},
                    "outputs_schema": {"type": "object"},
                    "capabilities": ["obsidian.read"],
                    "side_effects": [],
                    "autonomy": "L1",
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

    registry = SkillRegistryLoader(
        base_path=registry_path,
        overlay_paths=[],
        capability_path=capabilities_path,
        op_registry_path=op_registry_path,
    )
    registry.load()
    runtime = SkillRuntime(
        registry=registry,
        policy=DefaultPolicy(),
        adapters={"python": DummyAdapter()},
    )
    composer = SkillComposer(runtime)

    parent_context = SkillContext({"obsidian.read"})
    parent_skill = registry.get_skill("parent_skill")

    with pytest.raises(SkillRuntimeError):
        await composer.invoke(parent_skill, parent_context, "writer", {})
