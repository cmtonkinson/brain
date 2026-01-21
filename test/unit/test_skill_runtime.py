"""Unit tests for skill runtime execution and validation."""

import json
from pathlib import Path

import pytest

from skills.approvals import ApprovalProposal, InMemoryApprovalRecorder
from skills.context import SkillContext
from skills.errors import SkillPolicyError, SkillValidationError
from skills.policy import DefaultPolicy
from skills.registry import SkillRegistryLoader
from skills.registry_schema import AutonomyLevel
from skills.runtime import SkillRuntime


class DummyAdapter:
    """Simple adapter that returns a fixed output."""

    def __init__(self, output):
        """Initialize the adapter with a static output."""
        self._output = output

    async def execute(self, skill, inputs, context, invoker=None):
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
                    "name": "search_notes",
                    "version": "1.0.0",
                    "status": status,
                    "description": "Search notes",
                    "kind": "logic",
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
                    "entrypoint": {
                        "runtime": "python",
                        "module": "skills.search_notes",
                        "handler": "run",
                    },
                    "call_targets": [{"kind": "op", "name": "dummy_op", "version": "1.0.0"}],
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

    loader = SkillRegistryLoader(
        base_path=registry_path,
        overlay_paths=[],
        capability_path=capabilities_path,
        op_registry_path=op_registry_path,
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
    context = SkillContext(
        allowed_capabilities={"obsidian.read"},
        actor="user",
        channel="cli",
    )

    with pytest.raises(SkillValidationError):
        await runtime.execute("search_notes", {}, context)


@pytest.mark.asyncio
async def test_runtime_executes_successfully(tmp_path):
    """Ensure enabled skills execute and return outputs."""
    loader = _setup_registry(
        tmp_path,
        {"type": "object", "required": ["results"], "properties": {"results": {"type": "array"}}},
    )
    runtime = SkillRuntime(
        registry=loader,
        policy=DefaultPolicy(),
        adapters={"python": DummyAdapter({"results": []})},
    )
    context = SkillContext(
        allowed_capabilities={"obsidian.read"},
        confirmed=True,
        actor="user",
        channel="cli",
    )

    result = await runtime.execute("search_notes", {"query": "hi"}, context)

    assert result.output == {"results": []}


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
    context = SkillContext(
        allowed_capabilities={"obsidian.read"},
        confirmed=True,
        actor="user",
        channel="cli",
    )

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
    context = SkillContext(
        allowed_capabilities=set(),
        actor="user",
        channel="cli",
    )

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
    context = SkillContext(
        allowed_capabilities={"obsidian.read"},
        actor="user",
        channel="cli",
    )

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
        op_registry_path=tmp_path / "op-registry.json",
    )
    loader.load()
    runtime = SkillRuntime(
        registry=loader,
        policy=DefaultPolicy(),
        adapters={"python": DummyAdapter({"results": []})},
    )
    context = SkillContext(
        allowed_capabilities={"obsidian.read"},
        channel="signal",
        actor="user",
    )

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
        actor="user",
        channel="cli",
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
    context = SkillContext(
        allowed_capabilities={"obsidian.read"},
        actor="user",
        channel="cli",
    )

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
    context = SkillContext(
        allowed_capabilities={"obsidian.read"},
        actor="user",
        channel="cli",
    )

    with pytest.raises(SkillValidationError):
        await runtime.execute("search_notes", {"query": "hi", "extra": "nope"}, context)


@pytest.mark.asyncio
async def test_runtime_records_approval_proposal(tmp_path: Path) -> None:
    """Ensure approval-required denials generate proposals."""
    loader = _setup_registry(
        tmp_path,
        {"type": "object", "required": ["results"], "properties": {"results": {"type": "array"}}},
    )
    proposals: list[str] = []

    async def _capture(
        proposal: ApprovalProposal,
        context: SkillContext,
    ) -> None:
        """Collect proposal identifiers for assertions."""
        proposals.append(proposal.proposal_id)
        return None

    recorder = InMemoryApprovalRecorder()
    runtime = SkillRuntime(
        registry=loader,
        policy=DefaultPolicy(),
        adapters={"python": DummyAdapter({"results": []})},
        approval_router=_capture,
        approval_recorder=recorder,
    )
    context = SkillContext(
        allowed_capabilities={"obsidian.read"},
        actor="user",
        channel="cli",
    )

    with pytest.raises(SkillPolicyError):
        await runtime.execute("search_notes", {"query": "hi"}, context)

    assert recorder.proposals
    assert proposals
