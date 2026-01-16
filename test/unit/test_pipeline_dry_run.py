import json
from pathlib import Path

import pytest

from test.skills.harness import DryRunResult, SkillTestHarness


def _write_json(path: Path, data: dict) -> None:
    """Serialize JSON test data to disk."""
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest.mark.asyncio
async def test_pipeline_dry_run_wiring(tmp_path):
    """Ensure pipeline dry-run exercises wiring and data flow."""
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
                            "outputs": {"content": "$step.read.content"}
                        },
                        {
                            "id": "summarize",
                            "target": {"kind": "op", "name": "summarize_op", "version": "1.0.0"},
                            "inputs": {"text": "$step.read.content"},
                            "outputs": {"summary": "$outputs.summary"}
                        }
                    ],
                    "failure_modes": [
                        {
                            "code": "pipeline_failed",
                            "description": "Pipeline execution failed.",
                            "retryable": False
                        }
                    ]
                }
            ]
        },
    )

    harness = SkillTestHarness(
        registry_path=skill_registry,
        capabilities_path=capabilities_path,
        overlay_paths=[],
        op_registry_path=op_registry,
    )

    result = await harness.run(
        "summarize_note_pipeline",
        {"path": "Notes/Test.md"},
        adapters={},
        allow_capabilities={"obsidian.read", "memory.propose"},
        dry_run=True,
        pipeline_step_results={
            "read": {"content": "hello"},
            "summarize": {"summary": "hi"},
        },
    )

    assert isinstance(result, DryRunResult)
    assert result.dry_run is True
