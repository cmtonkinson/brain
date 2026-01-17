"""Unit tests for pipeline schema compatibility checks."""

from skills.pipeline_validation import PipelineValidationContext, validate_pipeline_skill
from skills.registry_schema import (
    AutonomyLevel,
    CallTargetKind,
    CallTargetRef,
    Entrypoint,
    EntrypointRuntime,
    LogicSkillDefinition,
    OpDefinition,
    OpRuntime,
    PipelineSkillDefinition,
    SkillKind,
    SkillStatus,
)


def _make_logic_skill(name: str) -> LogicSkillDefinition:
    """Build a minimal logic skill definition for validation tests."""
    return LogicSkillDefinition(
        name=name,
        version="1.0.0",
        status=SkillStatus.enabled,
        description="Test skill",
        kind=SkillKind.logic,
        inputs_schema={"type": "object", "properties": {}},
        outputs_schema={"type": "object", "properties": {}},
        capabilities=["obsidian.read"],
        side_effects=[],
        autonomy=AutonomyLevel.L1,
        entrypoint=Entrypoint(
            runtime=EntrypointRuntime.python,
            module="skills.test",
            handler="run",
        ),
        call_targets=[CallTargetRef(kind=CallTargetKind.op, name="test_op", version="1.0.0")],
        failure_modes=[
            {
                "code": "skill_unexpected_error",
                "description": "Unexpected skill failure.",
                "retryable": False,
            }
        ],
    )


def _make_op(
    name: str,
    inputs_schema: dict,
    outputs_schema: dict,
) -> OpDefinition:
    """Build a minimal op definition for validation tests."""
    return OpDefinition(
        name=name,
        version="1.0.0",
        status=SkillStatus.enabled,
        description="Test op",
        inputs_schema=inputs_schema,
        outputs_schema=outputs_schema,
        capabilities=["obsidian.read"],
        side_effects=[],
        autonomy=AutonomyLevel.L1,
        runtime=OpRuntime.native,
        module="json",
        handler="dumps",
        failure_modes=[
            {
                "code": "op_unexpected_error",
                "description": "Unexpected op failure.",
                "retryable": False,
            }
        ],
    )


def test_pipeline_validation_rejects_incompatible_input_types() -> None:
    """Ensure pipeline validation rejects incompatible input types."""
    pipeline = PipelineSkillDefinition(
        name="pipeline_test",
        version="1.0.0",
        status=SkillStatus.enabled,
        description="Pipeline test",
        kind=SkillKind.pipeline,
        inputs_schema={
            "type": "object",
            "required": ["count"],
            "properties": {"count": {"type": "string"}},
        },
        outputs_schema={
            "type": "object",
            "required": [],
            "properties": {},
        },
        capabilities=[],
        side_effects=[],
        autonomy=AutonomyLevel.L1,
        steps=[
            {
                "id": "step1",
                "target": {"kind": "op", "name": "test_op", "version": "1.0.0"},
                "inputs": {"count": "$inputs.count"},
                "outputs": {},
            }
        ],
        failure_modes=[
            {
                "code": "pipeline_failed",
                "description": "Pipeline failed.",
                "retryable": False,
            }
        ],
    )
    op = _make_op(
        "test_op",
        inputs_schema={
            "type": "object",
            "required": ["count"],
            "properties": {"count": {"type": "integer"}},
        },
        outputs_schema={"type": "object", "properties": {}},
    )

    context = PipelineValidationContext(
        skills_by_key={("logic_test", "1.0.0"): _make_logic_skill("logic_test")},
        ops_by_key={(op.name, op.version): op},
    )

    errors, _ = validate_pipeline_skill(pipeline, context)

    assert any("incompatible" in error for error in errors)


def test_pipeline_validation_rejects_incompatible_output_types() -> None:
    """Ensure pipeline validation rejects incompatible output types."""
    pipeline = PipelineSkillDefinition(
        name="pipeline_test",
        version="1.0.0",
        status=SkillStatus.enabled,
        description="Pipeline test",
        kind=SkillKind.pipeline,
        inputs_schema={
            "type": "object",
            "required": [],
            "properties": {},
        },
        outputs_schema={
            "type": "object",
            "required": ["count"],
            "properties": {"count": {"type": "string"}},
        },
        capabilities=[],
        side_effects=[],
        autonomy=AutonomyLevel.L1,
        steps=[
            {
                "id": "step1",
                "target": {"kind": "op", "name": "test_op", "version": "1.0.0"},
                "inputs": {},
                "outputs": {"count": "$outputs.count"},
            }
        ],
        failure_modes=[
            {
                "code": "pipeline_failed",
                "description": "Pipeline failed.",
                "retryable": False,
            }
        ],
    )
    op = _make_op(
        "test_op",
        inputs_schema={"type": "object", "properties": {}},
        outputs_schema={
            "type": "object",
            "required": ["count"],
            "properties": {"count": {"type": "integer"}},
        },
    )

    context = PipelineValidationContext(
        skills_by_key={("logic_test", "1.0.0"): _make_logic_skill("logic_test")},
        ops_by_key={(op.name, op.version): op},
    )

    errors, _ = validate_pipeline_skill(pipeline, context)

    assert any("incompatible" in error for error in errors)
