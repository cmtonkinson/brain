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


def test_discover_loads_valid_op_manifest_from_nested_group_directory(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "author/demo-echo",
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
    assert registry.resolve_manifest(capability_id="demo-echo") is not None


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


def test_discover_rejects_duplicate_capability_ids_across_groups(tmp_path) -> None:
    manifest = {
        "capability_id": "demo-echo",
        "kind": "native_op",
        "version": "1.0.0",
        "summary": "Echo",
        "input_schema": {"payload": "object | The payload to echo."},
        "output_schema": "object | The echoed payload.",
        "call_target": "state.echo",
    }
    _write_manifest(tmp_path, "author-a/demo-echo", manifest)
    _write_manifest(tmp_path, "author-b/demo-echo", manifest)

    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="duplicate capability_id discovered"):
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


def test_pipeline_skill_requires_known_children_for_step_objects(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-pipeline",
        {
            "capability_id": "demo-pipeline",
            "kind": "pipeline_skill",
            "version": "1.0.0",
            "summary": "Pipeline",
            "pipeline": [
                {
                    "capability": "missing-capability",
                    "input_mapping": {
                        "text": "content",
                    },
                }
            ],
        },
    )

    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="unknown capability"):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_discover_skips_disabled_pipeline_with_unknown_members(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-pipeline",
        {
            "capability_id": "demo-pipeline",
            "kind": "pipeline_skill",
            "version": "1.0.0",
            "summary": "Pipeline",
            "enabled": False,
            "pipeline": ["missing-capability"],
        },
    )

    registry = CapabilityRegistry()
    registry.discover(root=tmp_path, call_targets=_discover_call_targets())

    assert registry.count() == 0
    assert registry.resolve_manifest(capability_id="demo-pipeline") is None


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


def test_discover_rejects_field_alias_shorthand_for_non_pipeline_capability(
    tmp_path,
) -> None:
    _write_manifest(
        tmp_path,
        "demo-invalid-alias",
        {
            "capability_id": "demo-invalid-alias",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Invalid alias",
            "input_schema": {"text": "string | from=content | Wrong here."},
            "call_target": "state.echo",
        },
    )

    registry = CapabilityRegistry()
    with pytest.raises(
        Exception,
        match="Field alias modifier 'from=' is only allowed for pipeline skills",
    ):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_discover_rejects_canonical_field_alias_for_non_pipeline_skill(
    tmp_path,
) -> None:
    _write_manifest(
        tmp_path,
        "demo-logic",
        {
            "capability_id": "demo-logic",
            "kind": "logic_skill",
            "version": "1.0.0",
            "summary": "Logic",
            "input_schema": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "x-from": "content",
                    }
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    )

    registry = CapabilityRegistry()
    with pytest.raises(
        Exception,
        match="Schema field alias 'x-from' is only allowed for pipeline skills",
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


def test_discover_allows_required_capabilities_for_logic_skill(tmp_path) -> None:
    pkg = tmp_path / "demo-logic"
    (pkg / "test").mkdir(parents=True)
    (pkg / "capability.json").write_text(
        json.dumps(
            {
                "capability_id": "demo-logic",
                "kind": "logic_skill",
                "version": "1.0.0",
                "summary": "Logic",
                "required_capabilities": ["demo-echo"],
            }
        ),
        encoding="utf-8",
    )
    (pkg / "README.md").write_text("# Logic", encoding="utf-8")
    (pkg / "execute.py").write_text("def execute():\n    return {}\n", encoding="utf-8")
    (pkg / "test" / "test_demo_logic.py").write_text(
        "def test_placeholder():\n    assert True\n",
        encoding="utf-8",
    )

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

    assert registry.resolve_manifest(capability_id="demo-logic") is not None


def test_discover_rejects_required_capabilities_for_native_op(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-echo",
        {
            "capability_id": "demo-echo",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Echo",
            "required_capabilities": ["demo-other"],
            "input_schema": {"payload": "object | The payload to echo."},
            "output_schema": "object | The echoed payload.",
            "call_target": "state.echo",
        },
    )

    registry = CapabilityRegistry()
    with pytest.raises(
        Exception,
        match="required_capabilities is only allowed for logic skills",
    ):
        registry.discover(root=tmp_path, call_targets=_discover_call_targets())


def test_discover_rejects_required_capabilities_for_pipeline_skill(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-pipeline",
        {
            "capability_id": "demo-pipeline",
            "kind": "pipeline_skill",
            "version": "1.0.0",
            "summary": "Pipeline",
            "required_capabilities": ["demo-echo"],
            "pipeline": ["demo-echo"],
        },
    )
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
    with pytest.raises(
        Exception,
        match="required_capabilities is only allowed for logic skills",
    ):
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


def test_discover_accepts_pipeline_handoff_when_producer_has_extra_fields(
    tmp_path,
) -> None:
    _write_manifest(
        tmp_path,
        "demo-first",
        {
            "capability_id": "demo-first",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "First",
            "input_schema": {"payload": "object"},
            "output_schema": {
                "payload": "object",
                "extra": "string | Extra producer-only field.",
            },
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
            "input_schema": {
                "payload": "object",
            },
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
            output_schema={
                "type": "object",
                "properties": {
                    "payload": {"type": "object"},
                    "extra": {"type": "string"},
                },
                "required": ["payload", "extra"],
                "additionalProperties": False,
            },
        ),
        "state.second": CallTargetContract(
            input_schema={
                "type": "object",
                "properties": {"payload": {"type": "object"}},
                "required": ["payload"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
        ),
    }
    registry = CapabilityRegistry()
    registry.discover(root=tmp_path, call_targets=call_targets)

    assert registry.resolve_manifest(capability_id="demo-pipeline") is not None


def test_discover_accepts_pipeline_step_input_mapping(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-first",
        {
            "capability_id": "demo-first",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "First",
            "input_schema": {"seed": "string"},
            "output_schema": {"content": "string | Body text."},
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
            "input_schema": {"text": "string | Text to chunk."},
            "output_schema": {"embedding_count": "integer"},
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
            "input_schema": {"seed": "string"},
            "output_schema": {"count": "integer | from=embedding_count"},
            "pipeline": [
                "demo-first",
                {
                    "capability": "demo-second",
                    "input_mapping": {
                        "text": "content",
                    },
                },
            ],
        },
    )

    call_targets = {
        "state.first": CallTargetContract(
            input_schema={
                "type": "object",
                "properties": {"seed": {"type": "string"}},
                "required": ["seed"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"],
                "additionalProperties": False,
            },
        ),
        "state.second": CallTargetContract(
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {"embedding_count": {"type": "integer"}},
                "required": ["embedding_count"],
                "additionalProperties": False,
            },
        ),
    }
    registry = CapabilityRegistry()
    registry.discover(root=tmp_path, call_targets=call_targets)

    assert registry.resolve_manifest(capability_id="demo-pipeline") is not None


def test_discover_rejects_pipeline_step_input_mapping_to_unknown_input_field(
    tmp_path,
) -> None:
    _write_manifest(
        tmp_path,
        "demo-first",
        {
            "capability_id": "demo-first",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "First",
            "input_schema": {"seed": "string"},
            "output_schema": {"content": "string"},
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
            "input_schema": {"text": "string"},
            "output_schema": {"embedding_count": "integer"},
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
            "input_schema": {"seed": "string"},
            "output_schema": {"embedding_count": "integer"},
            "pipeline": [
                "demo-first",
                {
                    "capability": "demo-second",
                    "input_mapping": {
                        "missing": "content",
                    },
                },
            ],
        },
    )

    call_targets = {
        "state.first": CallTargetContract(
            input_schema={
                "type": "object",
                "properties": {"seed": {"type": "string"}},
                "required": ["seed"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"],
                "additionalProperties": False,
            },
        ),
        "state.second": CallTargetContract(
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {"embedding_count": {"type": "integer"}},
                "required": ["embedding_count"],
                "additionalProperties": False,
            },
        ),
    }

    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="unknown input field missing"):
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


def test_discover_accepts_equivalent_nullable_type_encodings(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-nullable",
        {
            "capability_id": "demo-nullable",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Nullable",
            "input_schema": {"value": "integer | null | A nullable integer payload."},
            "output_schema": "integer | null | A nullable integer result.",
            "call_target": "state.nullable",
        },
    )
    registry = CapabilityRegistry()
    registry.discover(
        root=tmp_path,
        call_targets={
            "state.nullable": CallTargetContract(
                input_schema={
                    "type": "object",
                    "properties": {
                        "value": {"anyOf": [{"type": "integer"}, {"type": "null"}]}
                    },
                    "required": ["value"],
                    "additionalProperties": False,
                },
                output_schema={"anyOf": [{"type": "integer"}, {"type": "null"}]},
            )
        },
    )

    assert registry.resolve_manifest(capability_id="demo-nullable") is not None


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
    with pytest.raises(ValueError, match="input schema does not satisfy first"):
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
    with pytest.raises(ValueError, match="output schema is not satisfied by final"):
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


def test_discover_skips_disabled_capabilities(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-active",
        {
            "capability_id": "demo-active",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Active",
            "input_schema": {"payload": "object | The payload."},
            "output_schema": "object | The result.",
            "call_target": "state.echo",
        },
    )
    _write_manifest(
        tmp_path,
        "demo-disabled",
        {
            "capability_id": "demo-disabled",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Disabled",
            "enabled": False,
            "input_schema": {"payload": "object | The payload."},
            "output_schema": "object | The result.",
            "call_target": "state.echo",
        },
    )

    registry = CapabilityRegistry()
    registry.discover(root=tmp_path, call_targets=_discover_call_targets())

    assert registry.count() == 1
    assert registry.resolve_manifest(capability_id="demo-active") is not None
    assert registry.resolve_manifest(capability_id="demo-disabled") is None


def test_discover_accepts_detailed_schema_against_stub_contract(tmp_path) -> None:
    """A capability with detailed property schemas should pass validation
    when the auto-derived call target contract uses coarse type stubs
    (e.g. ``{"type": "object", "title": "SomeModel"}`` for Pydantic models).
    """
    # Simulate auto-derived stubs: the contract uses coarse types for complex
    # parameters (Sequence[FileEdit] → array of object stubs, return model → object stub).
    stub_targets = {
        "state.detailed": CallTargetContract(
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "edits": {
                        "type": "array",
                        "items": {"type": "object", "title": "FileEdit"},
                    },
                },
                "required": ["file_path", "edits"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "title": "VaultFileRecord"},
        ),
    }

    _write_manifest(
        tmp_path,
        "demo-detailed",
        {
            "capability_id": "demo-detailed",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Detailed schema op",
            "input_schema": {
                "file_path": "string | The path.",
                "edits": {
                    "type": "array",
                    "description": "Edits to apply.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start_line": {"type": "integer"},
                            "end_line": {"type": "integer"},
                            "content": {"type": "string"},
                        },
                        "required": ["start_line", "end_line", "content"],
                    },
                },
            },
            "output_schema": {
                "path": "string | The file path.",
                "content": "string | The content.",
                "revision": "string | The revision.",
            },
            "call_target": "state.detailed",
        },
    )

    registry = CapabilityRegistry()
    registry.discover(root=tmp_path, call_targets=stub_targets)

    assert registry.count() == 1


def test_discover_rejects_truly_incompatible_schema_against_stub(tmp_path) -> None:
    """A capability whose type fundamentally mismatches the contract should
    still be rejected even when the contract is a stub.
    """
    stub_targets = {
        "state.typed": CallTargetContract(
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
            output_schema={"type": "array", "title": "SomeList"},
        ),
    }

    _write_manifest(
        tmp_path,
        "demo-wrong-type",
        {
            "capability_id": "demo-wrong-type",
            "kind": "native_op",
            "version": "1.0.0",
            "summary": "Wrong output type",
            "input_schema": {"name": "string | The name."},
            "output_schema": {
                "path": "string | A path.",
            },
            "call_target": "state.typed",
        },
    )

    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="output schema does not match"):
        registry.discover(root=tmp_path, call_targets=stub_targets)
