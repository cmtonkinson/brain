import json
from pathlib import Path

from skills.registry_validation import (
    RegistryIndex,
    validate_overlay_data,
    validate_registry_data,
)


def test_registry_rejects_unknown_capability(tmp_path):
    """Ensure validation rejects unknown capabilities."""
    registry = {
        "registry_version": "1.0.0",
        "skills": [
            {
                "name": "search_notes",
                "version": "1.0.0",
                "status": "enabled",
                "description": "Search notes",
                "inputs_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
                "outputs_schema": {"type": "object", "properties": {"results": {"type": "array"}}},
                "capabilities": ["unknown.cap"],
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
            }
        ],
    }
    capability_ids = {"obsidian.read"}

    errors = validate_registry_data(registry, capability_ids)

    assert any("unknown capability" in error for error in errors)


def test_registry_rejects_duplicate_entries():
    """Ensure duplicate skill entries are detected."""
    registry = {
        "registry_version": "1.0.0",
        "skills": [
            {
                "name": "search_notes",
                "version": "1.0.0",
                "status": "enabled",
                "description": "Search notes",
                "inputs_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
                "outputs_schema": {"type": "object", "properties": {"results": {"type": "array"}}},
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
                "version": "1.0.0",
                "status": "enabled",
                "description": "Search notes",
                "inputs_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
                "outputs_schema": {"type": "object", "properties": {"results": {"type": "array"}}},
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
    }
    capability_ids = {"obsidian.read"}

    errors = validate_registry_data(registry, capability_ids)

    assert any("duplicate" in error for error in errors)


def test_overlay_rejects_contract_fields():
    """Ensure overlays cannot mutate contract fields."""
    overlay = {
        "overlay_version": "1.0.0",
        "overrides": [
            {
                "name": "search_notes",
                "capabilities": ["obsidian.read"],
            }
        ],
    }

    errors = validate_overlay_data(overlay)

    assert any("unexpected overlay fields" in error for error in errors)


def test_overlay_requires_known_skill():
    """Ensure overlays reference known skills only."""
    registry = {
        "registry_version": "1.0.0",
        "skills": [
            {
                "name": "search_notes",
                "version": "1.0.0",
                "status": "enabled",
                "description": "Search notes",
                "inputs_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
                "outputs_schema": {"type": "object", "properties": {"results": {"type": "array"}}},
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
            }
        ],
    }
    registry_index = RegistryIndex({"search_notes": {"1.0.0"}})
    overlay = {
        "overlay_version": "1.0.0",
        "overrides": [
            {
                "name": "unknown_skill",
                "status": "disabled",
            }
        ],
    }

    errors = validate_overlay_data(overlay, registry_index)

    assert any("unknown skill" in error for error in errors)
