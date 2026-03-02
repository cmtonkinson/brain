"""Unit tests for capability manifest discovery and validation."""

from __future__ import annotations

import json

import pytest

from services.action.capability_engine.registry import (
    CallTargetContract,
    CapabilityRegistry,
)


def _write_manifest(
    tmp_path, package: str, payload: dict[str, object], *, with_readme: bool = True
) -> None:
    package_dir = tmp_path / package
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "capability.json").write_text(json.dumps(payload), encoding="utf-8")
    if with_readme:
        (package_dir / "README.md").write_text("# Capability", encoding="utf-8")


def _discover_call_targets() -> dict[str, CallTargetContract]:
    return {
        "state.echo": CallTargetContract(
            input_schema={
                "type": "object",
                "properties": {"payload": {"type": "object"}},
                "required": ["payload"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
        )
    }


def test_discover_loads_valid_op_manifest(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-echo",
        {
            "capability_id": "demo-echo",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Echo",
            "input_schema": {"payload": "object | The payload to echo."},
            "output_schema": "object | The echoed payload.",
            "call_target": "state.echo",
        },
    )

    registry = CapabilityRegistry()
    registry.discover(root=tmp_path, call_targets=_discover_call_targets())

    assert registry.count() == 1
    manifest = registry.resolve_manifest(capability_id="demo-echo")
    assert manifest is not None
    assert manifest.input_schema is not None
    assert manifest.input_schema["properties"]["payload"]["type"] == "object"


def test_discover_requires_matching_package_name(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "wrong-name",
        {
            "capability_id": "demo-echo",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Echo",
            "call_target": "state.echo",
        },
    )

    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="directory must match"):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_discover_requires_readme(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-echo",
        {
            "capability_id": "demo-echo",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Echo",
            "call_target": "state.echo",
        },
        with_readme=False,
    )

    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="missing README"):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_pipeline_skill_requires_known_children(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-pipeline",
        {
            "capability_id": "demo-pipeline",
            "kind": "pipeline_skill",
            "version": "1.0.0",
            "summary": "Pipeline",
            "pipeline": ["missing-capability"],
        },
    )

    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="unknown capability"):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_invalid_shorthand_schema_fails_discovery(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-invalid",
        {
            "capability_id": "demo-invalid",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Invalid",
            "input_schema": {"payload": 123},  # Invalid shorthand value
            "call_target": "state.echo",
        },
    )
    registry = CapabilityRegistry()
    # Pydantic validation error wraps the custom SchemaExpansionError
    with pytest.raises(
        Exception,
        match="Value for property 'payload' in shorthand object must be a string",
    ):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_logic_skill_requires_entrypoint_and_tests(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-logic",
        {
            "capability_id": "demo-logic",
            "kind": "logic_skill",
            "version": "1.0.0",
            "summary": "Logic",
        },
    )
    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="missing entrypoint"):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_discover_requires_known_op_call_target(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-unknown-target",
        {
            "capability_id": "demo-unknown-target",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Unknown target",
            "call_target": "state.missing",
        },
    )
    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="unknown call target"):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_discover_requires_op_io_to_match_call_target_contract(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-mismatch",
        {
            "capability_id": "demo-mismatch",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Mismatch",
            "input_schema": {"wrong_key": "string | This is not the right input"},
            "call_target": "state.echo",
        },
    )
    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="input schema does not match"):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_discover_requires_pipeline_io_chain_compatibility(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-first",
        {
            "capability_id": "demo-first",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "First",
            "input_schema": {"payload": "object"},
            "output_schema": "integer",
            "call_target": "state.first",
        },
    )
    _write_manifest(
        tmp_path,
        "demo-second",
        {
            "capability_id": "demo-second",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Second",
            "input_schema": "string",
            "output_schema": "object",
            "call_target": "state.second",
        },
    )
    _write_manifest(
        tmp_path,
        "demo-pipeline",
        {
            "capability_id": "demo-pipeline",
            "kind": "pipeline_skill",
            "version": "1.0.0",
            "summary": "Pipeline",
            "input_schema": {"payload": "object"},
            "output_schema": "object",
            "pipeline": ["demo-first", "demo-second"],
        },
    )

    call_targets = {
        "state.first": CallTargetContract(
            input_schema={
                "type": "object",
                "properties": {"payload": {"type": "object"}},
                "required": ["payload"],
                "additionalProperties": False,
            },
            output_schema={"type": "integer"},
        ),
        "state.second": CallTargetContract(
            input_schema={"type": "string"},
            output_schema={"type": "object"},
        ),
    }
    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="incompatible call targets"):
        registry.discover(root=tmp_path, call_targets=call_targets)


def test_discover_requires_op_output_schema_to_match_call_target(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-mismatch",
        {
            "capability_id": "demo-mismatch",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Mismatch",
            "input_schema": {"payload": "object | The payload."},
            "output_schema": "string | Wrong output type.",
            "call_target": "state.echo",
        },
    )
    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="output schema does not match"):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_discover_rejects_pipeline_input_mismatch_with_first_step(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-step",
        {
            "capability_id": "demo-step",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Step",
            "input_schema": {"payload": "object"},
            "output_schema": "object",
            "call_target": "state.echo",
        },
    )
    _write_manifest(
        tmp_path,
        "demo-pipeline",
        {
            "capability_id": "demo-pipeline",
            "kind": "pipeline_skill",
            "version": "1.0.0",
            "summary": "Pipeline",
            "input_schema": "string | Wrong input type.",
            "output_schema": "object",
            "pipeline": ["demo-step"],
        },
    )

    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="input schema must match first"):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_discover_rejects_pipeline_output_mismatch_with_last_step(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-step",
        {
            "capability_id": "demo-step",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Step",
            "input_schema": {"payload": "object"},
            "output_schema": "object",
            "call_target": "state.echo",
        },
    )
    _write_manifest(
        tmp_path,
        "demo-pipeline",
        {
            "capability_id": "demo-pipeline",
            "kind": "pipeline_skill",
            "version": "1.0.0",
            "summary": "Pipeline",
            "input_schema": {"payload": "object"},
            "output_schema": "integer | Wrong output type.",
            "pipeline": ["demo-step"],
        },
    )

    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="output schema must match final"):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_discover_rejects_empty_pipeline(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-empty-pipe",
        {
            "capability_id": "demo-empty-pipe",
            "kind": "pipeline_skill",
            "version": "1.0.0",
            "summary": "Empty pipeline",
            "pipeline": [],
        },
    )
    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="must declare pipeline entries"):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_logic_skill_requires_tests(tmp_path) -> None:
    pkg = tmp_path / "demo-logic"
    pkg.mkdir()
    (pkg / "capability.json").write_text(
        json.dumps(
            {
                "capability_id": "demo-logic",
                "kind": "logic_skill",
                "version": "1.0.0",
                "summary": "Logic",
            }
        ),
        encoding="utf-8",
    )
    (pkg / "README.md").write_text("# Logic", encoding="utf-8")
    (pkg / "execute.py").write_text("# entrypoint", encoding="utf-8")

    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="missing tests"):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())
