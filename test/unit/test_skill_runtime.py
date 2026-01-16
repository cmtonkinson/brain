import json
from pathlib import Path

import pytest

from skills.context import SkillContext
from skills.policy import DefaultPolicy
from skills.registry import SkillRegistryLoader
from skills.registry_schema import AutonomyLevel
from skills.runtime import SkillPolicyError, SkillRuntime, SkillValidationError


class DummyAdapter:
    """Simple adapter that returns a fixed output."""

    def __init__(self, output):
        """Initialize the adapter with a static output."""
        self._output = output

    async def execute(self, skill, inputs, context):
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
) -> SkillRegistryLoader:
    """Create a temporary registry for runtime validation tests."""
    registry_path = tmp_path / "skill-registry.json"
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
                    "name": "search_notes",
                    "version": "1.0.0",
                    "status": status,
                    "description": "Search notes",
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
                    "entrypoint": {"runtime": "python", "module": "skills.search_notes", "handler": "run"},
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

    loader = SkillRegistryLoader(
        base_path=registry_path,
        overlay_paths=[],
        capability_path=capabilities_path,
    )
    loader.load()
    return loader


@pytest.mark.asyncio
async def test_runtime_validates_inputs(tmp_path):
    """Ensure input schema validation rejects missing fields."""
    loader = _setup_registry(
        tmp_path,
        {"type": "object", "required": ["results"], "properties": {"results": {"type": "array"}}},
    )
    runtime = SkillRuntime(
        registry=loader,
        policy=DefaultPolicy(),
        adapters={"python": DummyAdapter({"results": []})},
    )
    context = SkillContext(allowed_capabilities={"obsidian.read"})

    with pytest.raises(SkillValidationError):
        await runtime.execute("search_notes", {}, context)


@pytest.mark.asyncio
async def test_runtime_validates_outputs(tmp_path):
    """Ensure output schema validation rejects invalid types."""
    loader = _setup_registry(
        tmp_path,
        {"type": "object", "required": ["results"], "properties": {"results": {"type": "array"}}},
    )
    runtime = SkillRuntime(
        registry=loader,
        policy=DefaultPolicy(),
        adapters={"python": DummyAdapter({"results": "oops"})},
    )
    context = SkillContext(allowed_capabilities={"obsidian.read"})

    with pytest.raises(SkillValidationError):
        await runtime.execute("search_notes", {"query": "hi"}, context)


@pytest.mark.asyncio
async def test_runtime_denies_policy(tmp_path):
    """Ensure policy enforcement denies missing capabilities."""
    loader = _setup_registry(
        tmp_path,
        {"type": "object", "required": ["results"], "properties": {"results": {"type": "array"}}},
    )
    runtime = SkillRuntime(
        registry=loader,
        policy=DefaultPolicy(),
        adapters={"python": DummyAdapter({"results": []})},
    )
    context = SkillContext(allowed_capabilities=set())

    with pytest.raises(SkillPolicyError):
        await runtime.execute("search_notes", {"query": "hi"}, context)


@pytest.mark.asyncio
async def test_runtime_denies_disabled_skill(tmp_path):
    """Ensure disabled skills cannot execute."""
    loader = _setup_registry(
        tmp_path,
        {"type": "object", "required": ["results"], "properties": {"results": {"type": "array"}}},
        status="disabled",
    )
    runtime = SkillRuntime(
        registry=loader,
        policy=DefaultPolicy(),
        adapters={"python": DummyAdapter({"results": []})},
    )
    context = SkillContext(allowed_capabilities={"obsidian.read"})

    with pytest.raises(SkillPolicyError):
        await runtime.execute("search_notes", {"query": "hi"}, context)


@pytest.mark.asyncio
async def test_runtime_denies_channel_override(tmp_path):
    """Ensure channel allowlists deny invalid channels."""
    loader = _setup_registry(
        tmp_path,
        {"type": "object", "required": ["results"], "properties": {"results": {"type": "array"}}},
    )
    overlay_path = tmp_path / "skill-registry.local.yml"
    overlay_path.write_text(
        """
overlay_version: "1.0.0"
overrides:
  - name: search_notes
    channels:
      allow:
        - cli
""",
        encoding="utf-8",
    )
    loader = SkillRegistryLoader(
        base_path=tmp_path / "skill-registry.json",
        overlay_paths=[overlay_path],
        capability_path=tmp_path / "capabilities.json",
    )
    loader.load()
    runtime = SkillRuntime(
        registry=loader,
        policy=DefaultPolicy(),
        adapters={"python": DummyAdapter({"results": []})},
    )
    context = SkillContext(allowed_capabilities={"obsidian.read"}, channel="signal")

    with pytest.raises(SkillPolicyError):
        await runtime.execute("search_notes", {"query": "hi"}, context)


@pytest.mark.asyncio
async def test_runtime_enforces_autonomy_limit(tmp_path):
    """Ensure autonomy limits are enforced at runtime."""
    loader = _setup_registry(
        tmp_path,
        {"type": "object", "required": ["results"], "properties": {"results": {"type": "array"}}},
        autonomy="L2",
    )
    runtime = SkillRuntime(
        registry=loader,
        policy=DefaultPolicy(),
        adapters={"python": DummyAdapter({"results": []})},
    )
    context = SkillContext(
        allowed_capabilities={"obsidian.read"},
        max_autonomy=AutonomyLevel.L1,
    )

    with pytest.raises(SkillPolicyError):
        await runtime.execute("search_notes", {"query": "hi"}, context)


@pytest.mark.asyncio
async def test_runtime_validates_format(tmp_path):
    """Ensure format validators reject invalid inputs."""
    loader = _setup_registry(
        tmp_path,
        {"type": "object", "required": ["results"], "properties": {"results": {"type": "array"}}},
        inputs_schema={
            "type": "object",
            "required": ["url"],
            "properties": {"url": {"type": "string", "format": "uri"}},
        },
    )
    runtime = SkillRuntime(
        registry=loader,
        policy=DefaultPolicy(),
        adapters={"python": DummyAdapter({"results": []})},
    )
    context = SkillContext(allowed_capabilities={"obsidian.read"})

    with pytest.raises(SkillValidationError):
        await runtime.execute("search_notes", {"url": "not-a-url"}, context)


@pytest.mark.asyncio
async def test_runtime_rejects_unknown_fields(tmp_path):
    """Ensure unknown fields are rejected by schema validation."""
    loader = _setup_registry(
        tmp_path,
        {"type": "object", "required": ["results"], "properties": {"results": {"type": "array"}}},
        inputs_schema={
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
        },
    )
    runtime = SkillRuntime(
        registry=loader,
        policy=DefaultPolicy(),
        adapters={"python": DummyAdapter({"results": []})},
    )
    context = SkillContext(allowed_capabilities={"obsidian.read"})

    with pytest.raises(SkillValidationError):
        await runtime.execute("search_notes", {"query": "hi", "extra": "nope"}, context)
