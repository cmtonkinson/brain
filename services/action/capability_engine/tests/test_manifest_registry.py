"""Unit tests for capability manifest discovery and validation."""

from __future__ import annotations

import json

import pytest

from services.action.capability_engine.registry import CapabilityRegistry


def _write_manifest(
    tmp_path, package: str, payload: dict[str, object], *, with_readme: bool = True
) -> None:
    package_dir = tmp_path / package
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "capability.json").write_text(json.dumps(payload), encoding="utf-8")
    if with_readme:
        (package_dir / "README.md").write_text("# Capability", encoding="utf-8")


def test_discover_loads_valid_op_manifest(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-echo",
        {
            "capability_id": "demo-echo",
            "kind": "op",
            "version": "1.0.0",
            "summary": "Echo",
            "call_target": "state.echo",
        },
    )

    registry = CapabilityRegistry()
    registry.discover(root=tmp_path)

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
            "call_target": "state.echo",
        },
    )

    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="directory must match"):
        registry.discover(root=tmp_path)


def test_discover_requires_readme(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-echo",
        {
            "capability_id": "demo-echo",
            "kind": "op",
            "version": "1.0.0",
            "summary": "Echo",
            "call_target": "state.echo",
        },
        with_readme=False,
    )

    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="missing README"):
        registry.discover(root=tmp_path)


def test_pipeline_skill_requires_known_children(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-pipeline",
        {
            "capability_id": "demo-pipeline",
            "kind": "skill",
            "version": "1.0.0",
            "summary": "Pipeline",
            "skill_type": "pipeline",
            "pipeline": ["missing-capability"],
        },
    )

    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="unknown capability"):
        registry.discover(root=tmp_path)


def test_invalid_manifest_schema_fails_discovery(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-invalid",
        {
            "capability_id": "demo-invalid",
            "kind": "op",
            "version": "1.0.0",
            "call_target": "state.echo",
        },
    )
    registry = CapabilityRegistry()
    with pytest.raises(Exception):
        registry.discover(root=tmp_path)


def test_logic_skill_requires_entrypoint_and_tests(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-logic",
        {
            "capability_id": "demo-logic",
            "kind": "skill",
            "version": "1.0.0",
            "summary": "Logic",
            "skill_type": "logic",
        },
    )
    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="missing entrypoint"):
        registry.discover(root=tmp_path)
