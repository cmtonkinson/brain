import logging

from skills.audit import AuditLogger
from skills.context import SkillContext
from skills.op_audit import OpAuditLogger
from skills.registry import OpRuntimeEntry, SkillRuntimeEntry
from skills.registry_schema import (
    AutonomyLevel,
    CallTargetKind,
    CallTargetRef,
    Entrypoint,
    EntrypointRuntime,
    LogicSkillDefinition,
    OpDefinition,
    OpRuntime,
    SkillKind,
    SkillStatus,
)


def _make_skill_entry() -> SkillRuntimeEntry:
    """Build a SkillRuntimeEntry for audit tests."""
    definition = LogicSkillDefinition(
        name="search_notes",
        version="1.0.0",
        status=SkillStatus.enabled,
        description="Search",
        kind=SkillKind.logic,
        inputs_schema={"type": "object"},
        outputs_schema={"type": "object"},
        capabilities=["obsidian.read"],
        side_effects=[],
        autonomy=AutonomyLevel.L1,
        entrypoint=Entrypoint(runtime=EntrypointRuntime.python, module="x", handler="run"),
        call_targets=[CallTargetRef(kind=CallTargetKind.op, name="dummy_op", version="1.0.0")],
        failure_modes=[
            {
                "code": "skill_unexpected_error",
                "description": "Unexpected skill failure.",
                "retryable": False,
            }
        ],
    )
    return SkillRuntimeEntry(
        definition=definition,
        status=SkillStatus.enabled,
        autonomy=AutonomyLevel.L1,
        rate_limit=None,
        channels=None,
        actors=None,
    )


def _make_op_entry() -> OpRuntimeEntry:
    """Build an OpRuntimeEntry for audit tests."""
    definition = OpDefinition(
        name="dummy_op",
        version="1.0.0",
        status=SkillStatus.enabled,
        description="Dummy",
        inputs_schema={"type": "object"},
        outputs_schema={"type": "object"},
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
    return OpRuntimeEntry(
        definition=definition,
        status=SkillStatus.enabled,
        autonomy=AutonomyLevel.L1,
        rate_limit=None,
        channels=None,
        actors=None,
    )


def test_skill_audit_includes_trace_metadata(caplog):
    """Ensure audit events include trace and span metadata."""
    skill_entry = _make_skill_entry()
    parent_context = SkillContext({"obsidian.read"})
    child_context = parent_context.child({"obsidian.read"})

    logger = AuditLogger()
    with caplog.at_level(logging.INFO):
        logger.record(
            skill_entry,
            parent_context,
            status="success",
            duration_ms=1,
            policy_reasons=["ok"],
            policy_metadata={"actor": "user"},
        )
        logger.record(
            skill_entry,
            child_context,
            status="success",
            duration_ms=1,
            policy_reasons=["ok"],
            policy_metadata={"actor": "user"},
        )

    records = [r for r in caplog.records if r.message == "skill_audit"]
    parent_record = records[0].__dict__
    child_record = records[1].__dict__

    assert parent_record["trace_id"] == child_record["trace_id"]
    assert child_record["parent_invocation_id"] == parent_context.invocation_id
    assert parent_record["span_id"] == parent_context.invocation_id


def test_op_audit_includes_trace_metadata(caplog):
    """Ensure op audit events include trace and span metadata."""
    op_entry = _make_op_entry()
    parent_context = SkillContext({"obsidian.read"})
    child_context = parent_context.child({"obsidian.read"})

    logger = OpAuditLogger()
    with caplog.at_level(logging.INFO):
        logger.record(
            op_entry,
            parent_context,
            status="success",
            duration_ms=1,
            policy_reasons=["ok"],
            policy_metadata={"actor": "user"},
        )
        logger.record(
            op_entry,
            child_context,
            status="success",
            duration_ms=1,
            policy_reasons=["ok"],
            policy_metadata={"actor": "user"},
        )

    records = [r for r in caplog.records if r.message == "op_audit"]
    parent_record = records[0].__dict__
    child_record = records[1].__dict__

    assert parent_record["trace_id"] == child_record["trace_id"]
    assert child_record["parent_invocation_id"] == parent_context.invocation_id
    assert parent_record["span_id"] == parent_context.invocation_id
