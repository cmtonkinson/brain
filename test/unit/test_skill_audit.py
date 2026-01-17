"""Unit tests for skill audit logging."""

import logging

from skills.audit import AuditLogger
from skills.context import SkillContext
from skills.registry import SkillRuntimeEntry
from skills.registry_schema import (
    AutonomyLevel,
    CallTargetKind,
    CallTargetRef,
    Entrypoint,
    EntrypointRuntime,
    LogicSkillDefinition,
    Redaction,
    SkillKind,
    SkillStatus,
)


def test_audit_logger_redacts_fields(caplog):
    """Ensure audit logging redacts configured fields and logs side effects."""
    definition = LogicSkillDefinition(
        name="send_message",
        version="1.0.0",
        status=SkillStatus.enabled,
        description="Send message",
        kind=SkillKind.logic,
        inputs_schema={"type": "object"},
        outputs_schema={"type": "object"},
        capabilities=["messaging.send"],
        side_effects=["messaging.send"],
        autonomy=AutonomyLevel.L1,
        entrypoint=Entrypoint(runtime=EntrypointRuntime.python, module="x", handler="run"),
        redaction=Redaction(inputs=["body"], outputs=["message_id"]),
        call_targets=[CallTargetRef(kind=CallTargetKind.op, name="dummy_op", version="1.0.0")],
        failure_modes=[
            {
                "code": "skill_unexpected_error",
                "description": "Unexpected skill failure.",
                "retryable": False,
            }
        ],
    )
    skill = SkillRuntimeEntry(
        definition=definition,
        status=SkillStatus.enabled,
        autonomy=AutonomyLevel.L1,
        rate_limit=None,
        channels=None,
        actors=None,
    )
    context = SkillContext({"messaging.send"})

    logger = AuditLogger()
    with caplog.at_level(logging.INFO):
        logger.record(
            skill,
            context,
            status="success",
            duration_ms=12,
            inputs={"body": "secret", "recipient": "+1"},
            outputs={"message_id": "123"},
        )

    assert any("skill_audit" in record.message for record in caplog.records)
    record = next(r for r in caplog.records if r.message == "skill_audit")
    assert record.__dict__["inputs"]["body"] == "[REDACTED]"
    assert record.__dict__["outputs"]["message_id"] == "[REDACTED]"
    assert record.__dict__["side_effects"] == ["messaging.send"]
