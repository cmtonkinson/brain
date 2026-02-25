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
            input_types=("dict[str, object]",),
            output_types=("dict[str, object]",),
        )
    }


def test_discover_loads_valid_op_manifest(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-echo",
        {
            "capability_id": "demo-echo",
            "kind": "op",
            "version": "1.0.0",
            "summary": "Echo",
            "input_types": ["dict[str, object]"],
            "output_types": ["dict[str, object]"],
            "call_target": "state.echo",
        },
    )

    registry = CapabilityRegistry()
    registry.discover(root=tmp_path, call_targets=_discover_call_targets())

    assert registry.count() == 1
    assert registry.resolve_manifest(capability_id="demo-echo") is not None


def test_discover_requires_matching_package_name(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "wrong-name",
        {
            "capability_id": "demo-echo",
            "kind": "op",
            "version": "1.0.0",
            "summary": "Echo",
            "input_types": ["dict[str, object]"],
            "output_types": ["dict[str, object]"],
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
            "kind": "op",
            "version": "1.0.0",
            "summary": "Echo",
            "input_types": ["dict[str, object]"],
            "output_types": ["dict[str, object]"],
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
            "kind": "skill",
            "version": "1.0.0",
            "summary": "Pipeline",
            "input_types": ["dict[str, object]"],
            "output_types": ["dict[str, object]"],
            "skill_type": "pipeline",
            "pipeline": ["missing-capability"],
        },
    )

    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="unknown capability"):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_invalid_manifest_schema_fails_discovery(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-invalid",
        {
            "capability_id": "demo-invalid",
            "kind": "op",
            "version": "1.0.0",
            "input_types": ["dict[str, object]"],
            "output_types": ["dict[str, object]"],
            "call_target": "state.echo",
        },
    )
    registry = CapabilityRegistry()
    with pytest.raises(Exception):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_logic_skill_requires_entrypoint_and_tests(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-logic",
        {
            "capability_id": "demo-logic",
            "kind": "skill",
            "version": "1.0.0",
            "summary": "Logic",
            "input_types": ["dict[str, object]"],
            "output_types": ["dict[str, object]"],
            "skill_type": "logic",
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
            "kind": "op",
            "version": "1.0.0",
            "summary": "Unknown target",
            "input_types": ["dict[str, object]"],
            "output_types": ["dict[str, object]"],
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
            "kind": "op",
            "version": "1.0.0",
            "summary": "Mismatch",
            "input_types": ["str"],
            "output_types": ["dict[str, object]"],
            "call_target": "state.echo",
        },
    )
    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="input types do not match"):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_discover_requires_pipeline_io_chain_compatibility(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-first",
        {
            "capability_id": "demo-first",
            "kind": "op",
            "version": "1.0.0",
            "summary": "First",
            "input_types": ["dict[str, object]"],
            "output_types": ["int"],
            "call_target": "state.first",
        },
    )
    _write_manifest(
        tmp_path,
        "demo-second",
        {
            "capability_id": "demo-second",
            "kind": "op",
            "version": "1.0.0",
            "summary": "Second",
            "input_types": ["str"],
            "output_types": ["dict[str, object]"],
            "call_target": "state.second",
        },
    )
    _write_manifest(
        tmp_path,
        "demo-pipeline",
        {
            "capability_id": "demo-pipeline",
            "kind": "skill",
            "version": "1.0.0",
            "summary": "Pipeline",
            "input_types": ["dict[str, object]"],
            "output_types": ["dict[str, object]"],
            "skill_type": "pipeline",
            "pipeline": ["demo-first", "demo-second"],
        },
    )

    call_targets = {
        "state.first": CallTargetContract(
            input_types=("dict[str, object]",),
            output_types=("int",),
        ),
        "state.second": CallTargetContract(
            input_types=("str",),
            output_types=("dict[str, object]",),
        ),
    }
    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="incompatible call targets"):
        registry.discover(root=tmp_path, call_targets=call_targets)
