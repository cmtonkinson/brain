"""Unit tests for pipeline runtime execution."""

import json
from pathlib import Path

import pytest

from skills.context import SkillContext
from skills.op_runtime import OpRuntime, OpValidationError
from skills.policy import DefaultPolicy
from skills.registry import OpRegistryLoader, SkillRegistryLoader
from skills.runtime import SkillRuntime


class DummyOpAdapter:
    """Adapter stub for pipeline op execution tests."""

    def __init__(self, outputs_by_name: dict[str, dict[str, object]]) -> None:
        """Initialize the adapter with per-op outputs."""
        self._outputs_by_name = outputs_by_name

    async def execute(self, op_entry, inputs, context):
        """Return canned outputs keyed by op name."""
        return self._outputs_by_name[op_entry.definition.name]


def _write_json(path: Path, data: dict) -> None:
    """Serialize JSON test data to disk."""
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest.mark.asyncio
async def test_pipeline_runtime_executes_steps(tmp_path):
    """Ensure pipeline runtime executes steps and shapes outputs."""
    skill_registry = tmp_path / "skill-registry.json"
    op_registry = tmp_path / "op-registry.json"
    capabilities_path = tmp_path / "capabilities.json"

    _write_json(
        capabilities_path,
        {
            "version": "1.0.0",
            "capabilities": [
                {"id": "obsidian.read", "description": "", "group": "memory", "status": "active"},
                {"id": "memory.propose", "description": "", "group": "memory", "status": "active"},
            ],
        },
    )

    _write_json(
        op_registry,
        {
            "registry_version": "1.0.0",
            "ops": [
                {
                    "name": "read_note_op",
                    "version": "1.0.0",
                    "status": "enabled",
                    "description": "Read note",
                    "inputs_schema": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {"path": {"type": "string"}},
                    },
                    "outputs_schema": {
                        "type": "object",
                        "required": ["content"],
                        "properties": {"content": {"type": "string"}, "extra": {"type": "string"}},
                    },
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
                },
                {
                    "name": "summarize_op",
                    "version": "1.0.0",
                    "status": "enabled",
                    "description": "Summarize text",
                    "inputs_schema": {
                        "type": "object",
                        "required": ["text"],
                        "properties": {"text": {"type": "string"}},
                    },
                    "outputs_schema": {
                        "type": "object",
                        "required": ["summary"],
                        "properties": {"summary": {"type": "string"}},
                    },
                    "capabilities": ["memory.propose"],
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
                },
            ],
        },
    )

    _write_json(
        skill_registry,
        {
            "registry_version": "2.0.0",
            "skills": [
                {
                    "name": "summarize_note_pipeline",
                    "version": "1.0.0",
                    "status": "enabled",
                    "description": "Pipeline summary",
                    "kind": "pipeline",
                    "inputs_schema": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {"path": {"type": "string"}},
                    },
                    "outputs_schema": {
                        "type": "object",
                        "required": ["summary"],
                        "properties": {"summary": {"type": "string"}},
                    },
                    "capabilities": [],
                    "side_effects": [],
                    "autonomy": "L1",
                    "steps": [
                        {
                            "id": "read",
                            "target": {"kind": "op", "name": "read_note_op", "version": "1.0.0"},
                            "inputs": {"path": "$inputs.path"},
                            "outputs": {"content": "$step.read.content"},
                        },
                        {
                            "id": "summarize",
                            "target": {"kind": "op", "name": "summarize_op", "version": "1.0.0"},
                            "inputs": {"text": "$step.read.content"},
                            "outputs": {"summary": "$outputs.summary"},
                        },
                    ],
                    "failure_modes": [
                        {
                            "code": "pipeline_failed",
                            "description": "Pipeline execution failed.",
                            "retryable": False,
                        }
                    ],
                }
            ],
        },
    )

    op_loader = OpRegistryLoader(
        base_path=op_registry,
        overlay_paths=[],
        capability_path=capabilities_path,
    )
    op_loader.load()
    op_runtime = OpRuntime(
        registry=op_loader,
        policy=DefaultPolicy(),
        adapters={
            "native": DummyOpAdapter(
                {
                    "read_note_op": {"content": "hello", "extra": "ignore"},
                    "summarize_op": {"summary": "hi"},
                }
            )
        },
    )

    skill_loader = SkillRegistryLoader(
        base_path=skill_registry,
        overlay_paths=[],
        capability_path=capabilities_path,
        op_registry_path=op_registry,
    )
    skill_loader.load()
    runtime = SkillRuntime(
        registry=skill_loader,
        policy=DefaultPolicy(),
        adapters={},
        op_runtime=op_runtime,
    )

    result = await runtime.execute(
        "summarize_note_pipeline",
        {"path": "Notes/Test.md"},
        SkillContext(
            {"obsidian.read", "memory.propose"},
            confirmed=True,
            actor="user",
            channel="cli",
        ),
    )

    assert result.output == {"summary": "hi"}


@pytest.mark.asyncio
async def test_pipeline_runtime_missing_output_raises(tmp_path):
    """Ensure pipeline execution fails when a step omits required outputs."""
    skill_registry = tmp_path / "skill-registry.json"
    op_registry = tmp_path / "op-registry.json"
    capabilities_path = tmp_path / "capabilities.json"

    _write_json(
        capabilities_path,
        {
            "version": "1.0.0",
            "capabilities": [
                {"id": "obsidian.read", "description": "", "group": "memory", "status": "active"},
                {"id": "memory.propose", "description": "", "group": "memory", "status": "active"},
            ],
        },
    )

    _write_json(
        op_registry,
        {
            "registry_version": "1.0.0",
            "ops": [
                {
                    "name": "read_note_op",
                    "version": "1.0.0",
                    "status": "enabled",
                    "description": "Read note",
                    "inputs_schema": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {"path": {"type": "string"}},
                    },
                    "outputs_schema": {
                        "type": "object",
                        "required": ["content"],
                        "properties": {"content": {"type": "string"}},
                    },
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
                },
            ],
        },
    )

    _write_json(
        skill_registry,
        {
            "registry_version": "2.0.0",
            "skills": [
                {
                    "name": "summarize_note_pipeline",
                    "version": "1.0.0",
                    "status": "enabled",
                    "description": "Pipeline summary",
                    "kind": "pipeline",
                    "inputs_schema": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {"path": {"type": "string"}},
                    },
                    "outputs_schema": {
                        "type": "object",
                        "required": ["summary"],
                        "properties": {"summary": {"type": "string"}},
                    },
                    "capabilities": [],
                    "side_effects": [],
                    "autonomy": "L1",
                    "steps": [
                        {
                            "id": "read",
                            "target": {"kind": "op", "name": "read_note_op", "version": "1.0.0"},
                            "inputs": {"path": "$inputs.path"},
                            "outputs": {"content": "$outputs.summary"},
                        }
                    ],
                    "failure_modes": [
                        {
                            "code": "pipeline_failed",
                            "description": "Pipeline execution failed.",
                            "retryable": False,
                        }
                    ],
                }
            ],
        },
    )

    op_loader = OpRegistryLoader(
        base_path=op_registry,
        overlay_paths=[],
        capability_path=capabilities_path,
    )
    op_loader.load()
    op_runtime = OpRuntime(
        registry=op_loader,
        policy=DefaultPolicy(),
        adapters={"native": DummyOpAdapter({"read_note_op": {}})},
    )

    skill_loader = SkillRegistryLoader(
        base_path=skill_registry,
        overlay_paths=[],
        capability_path=capabilities_path,
        op_registry_path=op_registry,
    )
    skill_loader.load()
    runtime = SkillRuntime(
        registry=skill_loader,
        policy=DefaultPolicy(),
        adapters={},
        op_runtime=op_runtime,
    )

    with pytest.raises(OpValidationError, match="Missing required outputs"):
        await runtime.execute(
            "summarize_note_pipeline",
            {"path": "Notes/Test.md"},
            SkillContext(
                {"obsidian.read"},
                confirmed=True,
                actor="user",
                channel="cli",
            ),
        )
