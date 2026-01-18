"""Tests for the policy documentation generator."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.policy_doc_gen import generate_policy_docs


def _write_json(path: Path, payload: dict[str, object]) -> None:
    """Write JSON payload with UTF-8 encoding."""
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_policy_doc_generation_includes_overrides(tmp_path: Path) -> None:
    """Ensure policy docs include overlay-applied autonomy values."""
    skill_registry = {
        "registry_version": "1.0.0",
        "skills": [
            {
                "name": "read_note",
                "version": "1.0.0",
                "status": "enabled",
                "description": "Read a note.",
                "kind": "logic",
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
                "policy_tags": ["requires_review"],
                "entrypoint": {
                    "runtime": "python",
                    "module": "skills.read_note",
                    "handler": "run",
                },
                "call_targets": [{"kind": "op", "name": "read_note_op", "version": "1.0.0"}],
                "failure_modes": [
                    {
                        "code": "read_failed",
                        "description": "Read failed.",
                        "retryable": False,
                    }
                ],
            }
        ],
    }
    op_registry = {
        "registry_version": "1.0.0",
        "ops": [
            {
                "name": "read_note_op",
                "version": "1.0.0",
                "status": "enabled",
                "description": "Read a note.",
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
                "module": "skills.ops.read_note",
                "handler": "run",
                "failure_modes": [
                    {
                        "code": "op_failed",
                        "description": "Op failed.",
                        "retryable": False,
                    }
                ],
            }
        ],
    }
    skill_path = tmp_path / "skill-registry.json"
    op_path = tmp_path / "op-registry.json"
    overlay_path = tmp_path / "skill-registry.local.yml"
    _write_json(skill_path, skill_registry)
    _write_json(op_path, op_registry)
    overlay_path.write_text(
        "\n".join(
            [
                'overlay_version: "1.0.0"',
                "overrides:",
                "  - name: read_note",
                '    version: "1.0.0"',
                "    autonomy: L0",
            ]
        ),
        encoding="utf-8",
    )

    output = generate_policy_docs(
        skill_path,
        op_path,
        Path("config/capabilities.json"),
        [overlay_path],
        [],
    )

    assert "# Policy Documentation" in output
    assert "### skill:read_note@1.0.0" in output
    assert "autonomy: L0" in output
