"""Tests for the policy simulation tool."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.policy_simulate import simulate_policy_decision
from skills.registry_schema import AutonomyLevel


def _write_json(path: Path, payload: dict[str, object]) -> None:
    """Write JSON payload with UTF-8 encoding."""
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_policy_simulation_allows_confirmed_action(tmp_path: Path) -> None:
    """Ensure simulation returns an allowed decision when confirmed."""
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
                "policy_tags": [],
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
    _write_json(skill_path, skill_registry)
    _write_json(op_path, op_registry)

    result = simulate_policy_decision(
        kind="skill",
        name="read_note",
        version="1.0.0",
        actor="user",
        channel="cli",
        allowed_capabilities=None,
        max_autonomy=None,
        confirmed=True,
        dry_run=True,
        skill_registry_path=skill_path,
        op_registry_path=op_path,
        capabilities_path=Path("config/capabilities.json"),
        skill_overlays=[],
        op_overlays=[],
    )

    assert result["decision"] is True
    assert "policy.entry.autonomy" in result["metadata"]


def test_policy_simulation_denies_missing_capability(tmp_path: Path) -> None:
    """Ensure simulation denies actions when capabilities are missing."""
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
                "policy_tags": [],
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
    _write_json(skill_path, skill_registry)
    _write_json(op_path, op_registry)

    result = simulate_policy_decision(
        kind="skill",
        name="read_note",
        version="1.0.0",
        actor="user",
        channel="cli",
        allowed_capabilities={"other.cap"},
        max_autonomy=None,
        confirmed=True,
        dry_run=True,
        skill_registry_path=skill_path,
        op_registry_path=op_path,
        capabilities_path=Path("config/capabilities.json"),
        skill_overlays=[],
        op_overlays=[],
    )

    assert result["decision"] is False
    assert any("capability_not_allowed" in reason for reason in result["reasons"])


def test_policy_simulation_denies_unconfirmed_action(tmp_path: Path) -> None:
    """Ensure unconfirmed L1 actions are denied."""
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
                "policy_tags": [],
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
    _write_json(skill_path, skill_registry)
    _write_json(op_path, op_registry)

    result = simulate_policy_decision(
        kind="skill",
        name="read_note",
        version="1.0.0",
        actor="user",
        channel="cli",
        allowed_capabilities=None,
        max_autonomy=None,
        confirmed=False,
        dry_run=True,
        skill_registry_path=skill_path,
        op_registry_path=op_path,
        capabilities_path=Path("config/capabilities.json"),
        skill_overlays=[],
        op_overlays=[],
    )

    assert result["decision"] is False
    assert "approval_required" in result["reasons"]


def test_policy_simulation_denies_requires_review(tmp_path: Path) -> None:
    """Ensure review-required tags block unconfirmed actions."""
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
    _write_json(skill_path, skill_registry)
    _write_json(op_path, op_registry)

    result = simulate_policy_decision(
        kind="skill",
        name="read_note",
        version="1.0.0",
        actor="user",
        channel="cli",
        allowed_capabilities=None,
        max_autonomy=None,
        confirmed=False,
        dry_run=True,
        skill_registry_path=skill_path,
        op_registry_path=op_path,
        capabilities_path=Path("config/capabilities.json"),
        skill_overlays=[],
        op_overlays=[],
    )

    assert result["decision"] is False
    assert "review_required" in result["reasons"]


def test_policy_simulation_denies_autonomy_over_limit(tmp_path: Path) -> None:
    """Ensure autonomy limits deny higher-autonomy skills."""
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
                "autonomy": "L2",
                "policy_tags": [],
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
    _write_json(skill_path, skill_registry)
    _write_json(op_path, op_registry)

    result = simulate_policy_decision(
        kind="skill",
        name="read_note",
        version="1.0.0",
        actor="user",
        channel="cli",
        allowed_capabilities=None,
        max_autonomy=AutonomyLevel.L1,
        confirmed=True,
        dry_run=True,
        skill_registry_path=skill_path,
        op_registry_path=op_path,
        capabilities_path=Path("config/capabilities.json"),
        skill_overlays=[],
        op_overlays=[],
    )

    assert result["decision"] is False
    assert "autonomy_exceeds_limit" in result["reasons"]


def test_policy_simulation_denies_channel_not_allowed(tmp_path: Path) -> None:
    """Ensure channel allowlists deny disallowed channels."""
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
                "policy_tags": [],
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
                "    channels:",
                "      allow: [cli]",
            ]
        ),
        encoding="utf-8",
    )

    result = simulate_policy_decision(
        kind="skill",
        name="read_note",
        version="1.0.0",
        actor="user",
        channel="signal",
        allowed_capabilities=None,
        max_autonomy=None,
        confirmed=True,
        dry_run=True,
        skill_registry_path=skill_path,
        op_registry_path=op_path,
        capabilities_path=Path("config/capabilities.json"),
        skill_overlays=[overlay_path],
        op_overlays=[],
    )

    assert result["decision"] is False
    assert "channel_not_allowed" in result["reasons"]
