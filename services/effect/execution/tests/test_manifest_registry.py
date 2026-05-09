"""Unit tests for op manifest discovery and validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.effect.execution.registry import (
    CallTargetContract,
    OpRegistry,
)


def _write_manifest(
    tmp_path, package: str, payload: dict[str, object], *, with_readme: bool = True
) -> None:
    package_dir = tmp_path / package
    package_dir.mkdir(parents=True, exist_ok=True)
    normalized = {"effect": "read", "approval": "never", **payload}
    (package_dir / "op.json").write_text(json.dumps(normalized), encoding="utf-8")
    if with_readme:
        (package_dir / "README.md").write_text("# Op", encoding="utf-8")


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
            "op_id": "demo-echo",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Echo",
            "input_schema": {"payload": "object | The payload to echo."},
            "output_schema": "object | The echoed payload.",
            "call_target": "state.echo",
        },
    )

    registry = OpRegistry()
    registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())

    assert registry.count() == 1
    manifest = registry.resolve_manifest(op_id="demo-echo")
    assert manifest is not None
    assert manifest.input_schema is not None
    assert manifest.input_schema["properties"]["payload"]["type"] == "object"


def test_builtin_job_ops_are_discoverable() -> None:
    registry = OpRegistry()

    registry.discover(roots=(Path("ops"),))

    job_ops = {
        manifest.op_id: manifest
        for manifest in registry.list_manifests()
        if manifest.op_id.startswith("job-")
    }
    assert set(job_ops) == {
        "job-cancel",
        "job-create",
        "job-get",
        "job-list",
        "job-run-now",
    }
    assert job_ops["job-list"].effect == "read"
    assert job_ops["job-list"].approval == "never"
    assert job_ops["job-create"].effect == "write"
    assert job_ops["job-create"].approval == "always"


def test_builtin_commitment_ingestion_and_datetime_ops_are_discoverable() -> None:
    registry = OpRegistry()

    registry.discover(roots=(Path("ops"),))

    manifests = {manifest.op_id: manifest for manifest in registry.list_manifests()}
    for op_id in (
        "commitment-create",
        "commitment-list",
        "commitment-get",
        "commitment-update",
        "commitment-record-progress",
        "commitment-transition",
        "commitment-history",
        "ingestion-submit",
        "ingestion-status",
        "ingestion-results",
        "ingestion-list",
        "ingestion-retry",
        "ingestion-replay",
        "datetime-parse",
        "datetime-convert-timezone",
        "duration-until",
    ):
        assert op_id in manifests

    assert manifests["commitment-list"].effect == "read"
    assert manifests["commitment-create"].approval == "always"
    assert manifests["ingestion-submit"].approval == "always"
    assert manifests["ingestion-status"].approval == "never"
    assert manifests["datetime-parse"].approval == "never"


def test_discover_loads_valid_op_manifest_from_nested_group_directory(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "author/demo-echo",
        {
            "op_id": "demo-echo",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Echo",
            "input_schema": {"payload": "object | The payload to echo."},
            "output_schema": "object | The echoed payload.",
            "call_target": "state.echo",
        },
    )

    registry = OpRegistry()
    registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())

    assert registry.count() == 1
    assert registry.resolve_manifest(op_id="demo-echo") is not None


def test_discover_requires_matching_package_name(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "wrong-name",
        {
            "op_id": "demo-echo",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Echo",
            "call_target": "state.echo",
        },
    )

    registry = OpRegistry()
    with pytest.raises(ValueError, match="directory must match"):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_discover_requires_readme(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-echo",
        {
            "op_id": "demo-echo",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Echo",
            "call_target": "state.echo",
        },
        with_readme=False,
    )

    registry = OpRegistry()
    with pytest.raises(ValueError, match="missing README"):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_discover_rejects_duplicate_op_ids_across_groups(tmp_path) -> None:
    manifest = {
        "op_id": "demo-echo",
        "kind": "native",
        "version": "1.0.0",
        "summary": "Echo",
        "input_schema": {"payload": "object | The payload to echo."},
        "output_schema": "object | The echoed payload.",
        "call_target": "state.echo",
    }
    _write_manifest(tmp_path, "author-a/demo-echo", manifest)
    _write_manifest(tmp_path, "author-b/demo-echo", manifest)

    registry = OpRegistry()
    with pytest.raises(ValueError, match="duplicate op_id discovered"):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_discover_overlay_later_root_wins_on_op_id(tmp_path) -> None:
    builtin = tmp_path / "builtin"
    overlay = tmp_path / "overlay"
    _write_manifest(
        builtin,
        "demo-echo",
        {
            "op_id": "demo-echo",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Built-in echo",
            "input_schema": {"payload": "object | The payload to echo."},
            "output_schema": "object | The echoed payload.",
            "call_target": "state.echo",
        },
    )
    _write_manifest(
        overlay,
        "demo-echo",
        {
            "op_id": "demo-echo",
            "kind": "native",
            "version": "2.0.0",
            "summary": "Overlay echo",
            "input_schema": {"payload": "object | The payload to echo."},
            "output_schema": "object | The echoed payload.",
            "call_target": "state.echo",
        },
    )

    registry = OpRegistry()
    registry.discover(
        roots=(builtin, overlay),
        call_targets=_discover_call_targets(),
    )

    manifest = registry.resolve_manifest(op_id="demo-echo")
    assert manifest is not None
    assert manifest.summary == "Overlay echo"
    assert manifest.version == "2.0.0"


def test_discover_overlay_adds_new_op_ids(tmp_path) -> None:
    builtin = tmp_path / "builtin"
    overlay = tmp_path / "overlay"
    _write_manifest(
        builtin,
        "demo-echo",
        {
            "op_id": "demo-echo",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Echo",
            "input_schema": {"payload": "object | The payload to echo."},
            "output_schema": "object | The echoed payload.",
            "call_target": "state.echo",
        },
    )
    _write_manifest(
        overlay,
        "demo-only-overlay",
        {
            "op_id": "demo-only-overlay",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Overlay only",
            "input_schema": {"payload": "object | The payload to echo."},
            "output_schema": "object | The echoed payload.",
            "call_target": "state.echo",
        },
    )

    registry = OpRegistry()
    registry.discover(
        roots=(builtin, overlay),
        call_targets=_discover_call_targets(),
    )

    assert registry.resolve_manifest(op_id="demo-echo") is not None
    assert registry.resolve_manifest(op_id="demo-only-overlay") is not None


def test_discover_overlay_skips_missing_root(tmp_path) -> None:
    builtin = tmp_path / "builtin"
    overlay = tmp_path / "overlay"  # not created
    _write_manifest(
        builtin,
        "demo-echo",
        {
            "op_id": "demo-echo",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Echo",
            "input_schema": {"payload": "object | The payload to echo."},
            "output_schema": "object | The echoed payload.",
            "call_target": "state.echo",
        },
    )

    registry = OpRegistry()
    registry.discover(
        roots=(builtin, overlay),
        call_targets=_discover_call_targets(),
    )

    assert registry.resolve_manifest(op_id="demo-echo") is not None


def test_pipeline_op_requires_known_children(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-pipeline",
        {
            "op_id": "demo-pipeline",
            "kind": "pipeline",
            "version": "1.0.0",
            "summary": "Pipeline",
            "pipeline": ["missing-op"],
        },
    )

    registry = OpRegistry()
    with pytest.raises(ValueError, match="unknown op"):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_pipeline_op_requires_known_children_for_step_objects(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-pipeline",
        {
            "op_id": "demo-pipeline",
            "kind": "pipeline",
            "version": "1.0.0",
            "summary": "Pipeline",
            "pipeline": [
                {
                    "op": "missing-op",
                    "input_mapping": {
                        "text": "content",
                    },
                }
            ],
        },
    )

    registry = OpRegistry()
    with pytest.raises(ValueError, match="unknown op"):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_discover_skips_disabled_pipeline_with_unknown_members(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-pipeline",
        {
            "op_id": "demo-pipeline",
            "kind": "pipeline",
            "version": "1.0.0",
            "summary": "Pipeline",
            "enabled": False,
            "pipeline": ["missing-op"],
        },
    )

    registry = OpRegistry()
    registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())

    assert registry.count() == 0
    assert registry.resolve_manifest(op_id="demo-pipeline") is None


def test_invalid_shorthand_schema_fails_discovery(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-invalid",
        {
            "op_id": "demo-invalid",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Invalid",
            "input_schema": {"payload": 123},  # Invalid shorthand value
            "call_target": "state.echo",
        },
    )
    registry = OpRegistry()
    # Pydantic validation error wraps the custom SchemaExpansionError
    with pytest.raises(
        Exception,
        match="Value for property 'payload' in shorthand object must be a string",
    ):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_discover_rejects_field_alias_shorthand_for_non_pipeline_op(
    tmp_path,
) -> None:
    _write_manifest(
        tmp_path,
        "demo-invalid-alias",
        {
            "op_id": "demo-invalid-alias",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Invalid alias",
            "input_schema": {"text": "string | from=content | Wrong here."},
            "call_target": "state.echo",
        },
    )

    registry = OpRegistry()
    with pytest.raises(
        Exception,
        match="Field alias modifier 'from=' is only allowed for pipeline ops",
    ):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_discover_rejects_canonical_field_alias_for_non_pipeline_op(
    tmp_path,
) -> None:
    _write_manifest(
        tmp_path,
        "demo-logic",
        {
            "op_id": "demo-logic",
            "kind": "logic",
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

    registry = OpRegistry()
    with pytest.raises(
        Exception,
        match="Schema field alias 'x-from' is only allowed for pipeline ops",
    ):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_logic_op_requires_entrypoint_and_tests(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-logic",
        {
            "op_id": "demo-logic",
            "kind": "logic",
            "version": "1.0.0",
            "summary": "Logic",
        },
    )
    registry = OpRegistry()
    with pytest.raises(ValueError, match="missing entrypoint"):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_discover_allows_required_ops_for_logic_op(tmp_path) -> None:
    pkg = tmp_path / "demo-logic"
    (pkg / "test").mkdir(parents=True)
    (pkg / "op.json").write_text(
        json.dumps(
            {
                "op_id": "demo-logic",
                "kind": "logic",
                "version": "1.0.0",
                "summary": "Logic",
                "effect": "execute",
                "approval": "never",
                "required_ops": ["demo-echo"],
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
            "op_id": "demo-echo",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Echo",
            "input_schema": {"payload": "object | The payload to echo."},
            "output_schema": "object | The echoed payload.",
            "call_target": "state.echo",
        },
    )

    registry = OpRegistry()
    registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())

    assert registry.resolve_manifest(op_id="demo-logic") is not None


def test_discover_rejects_required_ops_for_native_op(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-echo",
        {
            "op_id": "demo-echo",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Echo",
            "required_ops": ["demo-other"],
            "input_schema": {"payload": "object | The payload to echo."},
            "output_schema": "object | The echoed payload.",
            "call_target": "state.echo",
        },
    )

    registry = OpRegistry()
    with pytest.raises(
        Exception,
        match="required_ops is only allowed for logic ops",
    ):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_discover_rejects_required_ops_for_pipeline_op(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-pipeline",
        {
            "op_id": "demo-pipeline",
            "kind": "pipeline",
            "version": "1.0.0",
            "summary": "Pipeline",
            "required_ops": ["demo-echo"],
            "pipeline": ["demo-echo"],
        },
    )
    _write_manifest(
        tmp_path,
        "demo-echo",
        {
            "op_id": "demo-echo",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Echo",
            "input_schema": {"payload": "object | The payload to echo."},
            "output_schema": "object | The echoed payload.",
            "call_target": "state.echo",
        },
    )

    registry = OpRegistry()
    with pytest.raises(
        Exception,
        match="required_ops is only allowed for logic ops",
    ):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_discover_requires_known_op_call_target(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-unknown-target",
        {
            "op_id": "demo-unknown-target",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Unknown target",
            "call_target": "state.missing",
        },
    )
    registry = OpRegistry()
    with pytest.raises(ValueError, match="unknown call target"):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_discover_requires_op_io_to_match_call_target_contract(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-mismatch",
        {
            "op_id": "demo-mismatch",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Mismatch",
            "input_schema": {"wrong_key": "string | This is not the right input"},
            "call_target": "state.echo",
        },
    )
    registry = OpRegistry()
    with pytest.raises(ValueError, match="input schema does not match"):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_discover_requires_pipeline_io_chain_compatibility(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-first",
        {
            "op_id": "demo-first",
            "kind": "native",
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
            "op_id": "demo-second",
            "kind": "native",
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
            "op_id": "demo-pipeline",
            "kind": "pipeline",
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
    registry = OpRegistry()
    with pytest.raises(ValueError, match="incompatible call targets"):
        registry.discover(roots=(tmp_path,), call_targets=call_targets)


def test_discover_accepts_pipeline_handoff_when_producer_has_extra_fields(
    tmp_path,
) -> None:
    _write_manifest(
        tmp_path,
        "demo-first",
        {
            "op_id": "demo-first",
            "kind": "native",
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
            "op_id": "demo-second",
            "kind": "native",
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
            "op_id": "demo-pipeline",
            "kind": "pipeline",
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
    registry = OpRegistry()
    registry.discover(roots=(tmp_path,), call_targets=call_targets)

    assert registry.resolve_manifest(op_id="demo-pipeline") is not None


def test_discover_accepts_pipeline_step_input_mapping(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-first",
        {
            "op_id": "demo-first",
            "kind": "native",
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
            "op_id": "demo-second",
            "kind": "native",
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
            "op_id": "demo-pipeline",
            "kind": "pipeline",
            "version": "1.0.0",
            "summary": "Pipeline",
            "input_schema": {"seed": "string"},
            "output_schema": {"count": "integer | from=embedding_count"},
            "pipeline": [
                "demo-first",
                {
                    "op": "demo-second",
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
    registry = OpRegistry()
    registry.discover(roots=(tmp_path,), call_targets=call_targets)

    assert registry.resolve_manifest(op_id="demo-pipeline") is not None


def test_discover_rejects_pipeline_step_input_mapping_to_unknown_input_field(
    tmp_path,
) -> None:
    _write_manifest(
        tmp_path,
        "demo-first",
        {
            "op_id": "demo-first",
            "kind": "native",
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
            "op_id": "demo-second",
            "kind": "native",
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
            "op_id": "demo-pipeline",
            "kind": "pipeline",
            "version": "1.0.0",
            "summary": "Pipeline",
            "input_schema": {"seed": "string"},
            "output_schema": {"embedding_count": "integer"},
            "pipeline": [
                "demo-first",
                {
                    "op": "demo-second",
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

    registry = OpRegistry()
    with pytest.raises(ValueError, match="unknown input field missing"):
        registry.discover(roots=(tmp_path,), call_targets=call_targets)


def test_discover_requires_op_output_schema_to_match_call_target(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-mismatch",
        {
            "op_id": "demo-mismatch",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Mismatch",
            "input_schema": {"payload": "object | The payload."},
            "output_schema": "string | Wrong output type.",
            "call_target": "state.echo",
        },
    )
    registry = OpRegistry()
    with pytest.raises(ValueError, match="output schema does not match"):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_discover_accepts_equivalent_nullable_type_encodings(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-nullable",
        {
            "op_id": "demo-nullable",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Nullable",
            "input_schema": {"value": "integer | null | A nullable integer payload."},
            "output_schema": "integer | null | A nullable integer result.",
            "call_target": "state.nullable",
        },
    )
    registry = OpRegistry()
    registry.discover(
        roots=(tmp_path,),
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

    assert registry.resolve_manifest(op_id="demo-nullable") is not None


def test_discover_rejects_pipeline_input_mismatch_with_first_step(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-step",
        {
            "op_id": "demo-step",
            "kind": "native",
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
            "op_id": "demo-pipeline",
            "kind": "pipeline",
            "version": "1.0.0",
            "summary": "Pipeline",
            "input_schema": "string | Wrong input type.",
            "output_schema": "object",
            "pipeline": ["demo-step"],
        },
    )

    registry = OpRegistry()
    with pytest.raises(ValueError, match="input schema does not satisfy first"):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_discover_rejects_pipeline_output_mismatch_with_last_step(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-step",
        {
            "op_id": "demo-step",
            "kind": "native",
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
            "op_id": "demo-pipeline",
            "kind": "pipeline",
            "version": "1.0.0",
            "summary": "Pipeline",
            "input_schema": {"payload": "object"},
            "output_schema": "integer | Wrong output type.",
            "pipeline": ["demo-step"],
        },
    )

    registry = OpRegistry()
    with pytest.raises(ValueError, match="output schema is not satisfied by final"):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_discover_rejects_empty_pipeline(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-empty-pipe",
        {
            "op_id": "demo-empty-pipe",
            "kind": "pipeline",
            "version": "1.0.0",
            "summary": "Empty pipeline",
            "pipeline": [],
        },
    )
    registry = OpRegistry()
    with pytest.raises(ValueError, match="must declare pipeline entries"):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_logic_op_requires_tests(tmp_path) -> None:
    pkg = tmp_path / "demo-logic"
    pkg.mkdir()
    (pkg / "op.json").write_text(
        json.dumps(
            {
                "op_id": "demo-logic",
                "kind": "logic",
                "version": "1.0.0",
                "summary": "Logic",
                "effect": "execute",
                "approval": "never",
            }
        ),
        encoding="utf-8",
    )
    (pkg / "README.md").write_text("# Logic", encoding="utf-8")
    (pkg / "execute.py").write_text("# entrypoint", encoding="utf-8")

    registry = OpRegistry()
    with pytest.raises(ValueError, match="missing tests"):
        registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())


def test_discover_skips_disabled_ops(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "demo-active",
        {
            "op_id": "demo-active",
            "kind": "native",
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
            "op_id": "demo-disabled",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Disabled",
            "enabled": False,
            "input_schema": {"payload": "object | The payload."},
            "output_schema": "object | The result.",
            "call_target": "state.echo",
        },
    )

    registry = OpRegistry()
    registry.discover(roots=(tmp_path,), call_targets=_discover_call_targets())

    assert registry.count() == 1
    assert registry.resolve_manifest(op_id="demo-active") is not None
    assert registry.resolve_manifest(op_id="demo-disabled") is None


def test_discover_accepts_detailed_schema_against_stub_contract(tmp_path) -> None:
    """An op with detailed property schemas should pass validation
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
            "op_id": "demo-detailed",
            "kind": "native",
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

    registry = OpRegistry()
    registry.discover(roots=(tmp_path,), call_targets=stub_targets)

    assert registry.count() == 1


def test_discover_rejects_truly_incompatible_schema_against_stub(tmp_path) -> None:
    """An op whose type fundamentally mismatches the contract should
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
            "op_id": "demo-wrong-type",
            "kind": "native",
            "version": "1.0.0",
            "summary": "Wrong output type",
            "input_schema": {"name": "string | The name."},
            "output_schema": {
                "path": "string | A path.",
            },
            "call_target": "state.typed",
        },
    )

    registry = OpRegistry()
    with pytest.raises(ValueError, match="output schema does not match"):
        registry.discover(roots=(tmp_path,), call_targets=stub_targets)
