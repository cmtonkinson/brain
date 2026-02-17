"""Unit tests for op audit logging."""

import logging

from skills.context import SkillContext
from skills.op_audit import OpAuditLogger
from skills.registry import OpRuntimeEntry
from skills.registry_schema import (
    AutonomyLevel,
    OpDefinition,
    OpRuntime,
    Redaction,
    SkillStatus,
)


def test_op_audit_logger_redacts_fields(caplog):
    """Ensure op audit logging redacts configured fields and logs side effects."""
    definition = OpDefinition(
        name="send_message",
        version="1.0.0",
        status=SkillStatus.enabled,
        description="Send message op",
        runtime=OpRuntime.native,
        module="skills.ops.messaging",
        handler="send_message",
        inputs_schema={"type": "object"},
        outputs_schema={"type": "object"},
        capabilities=["messaging.send"],
        side_effects=["messaging.send"],
        autonomy=AutonomyLevel.L1,
        redaction=Redaction(inputs=["body"], outputs=["message_id"]),
        failure_modes=[
            {
                "code": "op_unexpected_error",
                "description": "Unexpected op failure.",
                "retryable": False,
            }
        ],
    )
    op_entry = OpRuntimeEntry(
        definition=definition,
        status=SkillStatus.enabled,
        autonomy=AutonomyLevel.L1,
        rate_limit=None,
        channels=None,
        actors=None,
    )
    context = SkillContext({"messaging.send"})

    logger = OpAuditLogger()
    with caplog.at_level(logging.INFO):
        logger.record(
            op_entry,
            context,
            status="success",
            duration_ms=12,
            inputs={"body": "secret", "recipient": "+1"},
            outputs={"message_id": "123"},
        )

    assert any("op_audit" in record.message for record in caplog.records)
    record = next(r for r in caplog.records if r.message == "op_audit")
    assert record.__dict__["inputs"]["body"] == "[REDACTED]"
    assert record.__dict__["outputs"]["message_id"] == "[REDACTED]"
    assert record.__dict__["side_effects"] == ["messaging.send"]
