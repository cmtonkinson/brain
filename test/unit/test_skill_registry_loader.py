import json
from pathlib import Path

import pytest

from skills.registry import SkillRegistryLoader
from skills.registry_schema import SkillStatus


def _write_json(path: Path, data: dict) -> None:
    """Serialize JSON test data to disk."""
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_loader_applies_overrides_and_filters(tmp_path):
    """Ensure overlays adjust runtime fields and filters respond."""
    registry_path = tmp_path / "skill-registry.json"
    overlay_path = tmp_path / "skill-registry.local.yml"
    capabilities_path = tmp_path / "capabilities.json"

    _write_json(
        capabilities_path,
        {
            "version": "1.0.0",
            "capabilities": [
                {"id": "obsidian.read", "description": "", "group": "memory", "status": "active"},
                {"id": "vault.search", "description": "", "group": "memory", "status": "active"},
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
                    "status": "enabled",
                    "description": "Search notes",
                    "inputs_schema": {"type": "object"},
                    "outputs_schema": {"type": "object"},
                    "capabilities": ["obsidian.read", "vault.search"],
                    "side_effects": [],
                    "autonomy": "L1",
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

    overlay_path.write_text(
        "\n".join(
            [
                "overlay_version: \"1.0.0\"",
                "overrides:",
                "  - name: search_notes",
                "    status: disabled",
                "    autonomy: L0",
                "    rate_limit:",
                "      max_per_minute: 1",
            ]
        ),
        encoding="utf-8",
    )

    loader = SkillRegistryLoader(
        base_path=registry_path,
        overlay_paths=[overlay_path],
        capability_path=capabilities_path,
    )
    registry = loader.load()
    entry = registry.skills[0]

    assert entry.status == SkillStatus.disabled
    assert entry.autonomy.value == "L0"
    assert entry.rate_limit is not None
    assert entry.rate_limit.max_per_minute == 1

    assert loader.list_skills(status=SkillStatus.disabled)
    assert not loader.list_skills(capability="nonexistent")


def test_loader_filters_disabled_skills_without_entrypoints(tmp_path):
    """Ensure disabled skills with missing modules are skipped."""
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
                    "name": "disabled_skill",
                    "version": "1.0.0",
                    "status": "disabled",
                    "description": "Disabled",
                    "inputs_schema": {"type": "object"},
                    "outputs_schema": {"type": "object"},
                    "capabilities": ["obsidian.read"],
                    "side_effects": [],
                    "autonomy": "L1",
                    "entrypoint": {"runtime": "python", "module": "missing.module", "handler": "run"},
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
    registry = loader.load()

    assert registry.skills == []


def test_get_skill_requires_version_when_ambiguous(tmp_path):
    """Ensure ambiguous versions require explicit selection."""
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
                    "status": "enabled",
                    "description": "Search notes",
                    "inputs_schema": {"type": "object"},
                    "outputs_schema": {"type": "object"},
                    "capabilities": ["obsidian.read"],
                    "side_effects": [],
                    "autonomy": "L1",
                    "entrypoint": {"runtime": "python", "module": "x", "handler": "run"},
                    "failure_modes": [
                        {
                            "code": "skill_unexpected_error",
                            "description": "Unexpected skill failure.",
                            "retryable": False,
                        }
                    ],
                },
                {
                    "name": "search_notes",
                    "version": "1.1.0",
                    "status": "enabled",
                    "description": "Search notes",
                    "inputs_schema": {"type": "object"},
                    "outputs_schema": {"type": "object"},
                    "capabilities": ["obsidian.read"],
                    "side_effects": [],
                    "autonomy": "L1",
                    "entrypoint": {"runtime": "python", "module": "x", "handler": "run"},
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

    loader = SkillRegistryLoader(
        base_path=registry_path,
        overlay_paths=[],
        capability_path=capabilities_path,
    )
    loader.load()

    with pytest.raises(ValueError):
        loader.get_skill("search_notes")

    assert loader.get_skill("search_notes", "1.1.0").definition.version == "1.1.0"
