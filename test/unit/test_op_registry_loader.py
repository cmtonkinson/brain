"""Unit tests for op registry loading and overrides."""

import json
from pathlib import Path

from skills.registry import OpRegistryLoader
from skills.registry_schema import SkillStatus


def _write_json(path: Path, data: dict) -> None:
    """Serialize JSON test data to disk."""
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_op_loader_applies_overrides(tmp_path):
    """Ensure op overlays adjust runtime fields."""
    registry_path = tmp_path / "op-registry.json"
    overlay_path = tmp_path / "op-registry.local.yml"
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
                    "status": "enabled",
                    "description": "Search",
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

    overlay_path.write_text(
        "\n".join(
            [
                "overlay_version: \"1.0.0\"",
                "overrides:",
                "  - name: obsidian_search",
                "    status: disabled",
                "    autonomy: L0",
                "    rate_limit:",
                "      max_per_minute: 1",
            ]
        ),
        encoding="utf-8",
    )

    loader = OpRegistryLoader(
        base_path=registry_path,
        overlay_paths=[overlay_path],
        capability_path=capabilities_path,
    )
    registry = loader.load()
    entry = registry.ops[0]

    assert entry.status == SkillStatus.disabled
    assert entry.autonomy.value == "L0"
    assert entry.rate_limit is not None
    assert entry.rate_limit.max_per_minute == 1
