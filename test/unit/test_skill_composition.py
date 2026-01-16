import json
from pathlib import Path

import pytest

from skills.composition import SkillComposer
from skills.context import SkillContext
from skills.policy import DefaultPolicy
from skills.registry import SkillRegistryLoader
from skills.runtime import SkillPolicyError, SkillRuntime


class DummyAdapter:
    """Adapter stub for composition tests."""

    async def execute(self, skill, inputs, context):
        """Return a fixed response for test invocations."""
        return {"ok": True}


def _write_json(path: Path, data: dict) -> None:
    """Serialize JSON test data to disk."""
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest.mark.asyncio
async def test_child_skill_inherits_capability_limits(tmp_path):
    """Ensure child skills cannot exceed parent capability scopes."""
    registry_path = tmp_path / "skill-registry.json"
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
                    "name": "writer",
                    "version": "1.0.0",
                    "status": "enabled",
                    "description": "Write",
                    "inputs_schema": {"type": "object"},
                    "outputs_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
                    "capabilities": ["obsidian.write"],
                    "side_effects": ["obsidian.write"],
                    "autonomy": "L1",
                    "entrypoint": {"runtime": "python", "module": "x", "handler": "run"},
                    "failure_modes": [
                        {
                            "code": "skill_unexpected_error",
                            "description": "Unexpected skill failure.",
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
    )
    registry.load()
    runtime = SkillRuntime(
        registry=registry,
        policy=DefaultPolicy(),
        adapters={"python": DummyAdapter()},
    )
    composer = SkillComposer(runtime)

    parent_context = SkillContext({"obsidian.read"})

    with pytest.raises(SkillPolicyError):
        await composer.invoke(parent_context, "writer", {})
