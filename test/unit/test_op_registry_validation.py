"""Unit tests for op registry validation."""

from skills.registry_validation import validate_op_registry_data


def test_op_registry_rejects_unknown_capability():
    """Ensure op registry validation rejects unknown capabilities."""
    registry = {
        "registry_version": "1.0.0",
        "ops": [
            {
                "name": "obsidian_search",
                "version": "1.0.0",
                "status": "enabled",
                "description": "Search",
                "inputs_schema": {"type": "object"},
                "outputs_schema": {"type": "object"},
                "capabilities": ["unknown.cap"],
                "side_effects": [],
                "autonomy": "L1",
                "runtime": "native",
                "module": "ops.test",
                "handler": "run",
                "failure_modes": [
                    {
                        "code": "op_unexpected_error",
                        "description": "Unexpected op failure.",
                        "retryable": False,
                    }
                ],
            }
        ],
    }
    capability_ids = {"obsidian.read"}

    errors = validate_op_registry_data(registry, capability_ids)

    assert any("unknown capability" in error for error in errors)


def test_op_registry_rejects_duplicate_entries():
    """Ensure op registry validation rejects duplicate op entries."""
    registry = {
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
                "module": "ops.test",
                "handler": "run",
                "failure_modes": [
                    {
                        "code": "op_unexpected_error",
                        "description": "Unexpected op failure.",
                        "retryable": False,
                    }
                ],
            },
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
                "module": "ops.test",
                "handler": "run",
                "failure_modes": [
                    {
                        "code": "op_unexpected_error",
                        "description": "Unexpected op failure.",
                        "retryable": False,
                    }
                ],
            },
        ],
    }
    capability_ids = {"obsidian.read"}

    errors = validate_op_registry_data(registry, capability_ids)

    assert any("duplicate op entry" in error for error in errors)
