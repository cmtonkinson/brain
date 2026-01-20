"""Unit tests for read-only capability enforcement in predicate evaluation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scheduler.actor_context import (
    SCHEDULED_ACTOR_TYPE,
    SCHEDULED_AUTONOMY_LEVEL,
    SCHEDULED_CHANNEL,
    SCHEDULED_PRIVILEGE_LEVEL,
    ScheduledActorContext,
)
from scheduler.capability_gate import (
    READ_ONLY_CAPABILITIES,
    SIDE_EFFECTING_CAPABILITIES,
    CapabilityAuthorizationContext,
    CapabilityDecision,
    CapabilityDenialAuditRecord,
    CapabilityGate,
    CapabilityGateError,
    DenialReasonCode,
    create_predicate_evaluation_actor_context,
)


def _make_valid_actor_context(
    *,
    trace_id: str = "test-trace-001",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> CapabilityAuthorizationContext:
    """Create a valid scheduled actor context for tests."""
    return CapabilityAuthorizationContext(
        actor_type=SCHEDULED_ACTOR_TYPE,
        actor_id=actor_id,
        channel=SCHEDULED_CHANNEL,
        privilege_level=SCHEDULED_PRIVILEGE_LEVEL,
        autonomy_level=SCHEDULED_AUTONOMY_LEVEL,
        trace_id=trace_id,
        request_id=request_id,
    )


def _make_invalid_actor_context(
    *,
    actor_type: str = "user",
    channel: str = "api",
    privilege_level: str = "elevated",
    autonomy_level: str = "full",
    trace_id: str = "test-trace-002",
) -> CapabilityAuthorizationContext:
    """Create an invalid actor context for denial tests."""
    return CapabilityAuthorizationContext(
        actor_type=actor_type,
        actor_id=None,
        channel=channel,
        privilege_level=privilege_level,
        autonomy_level=autonomy_level,
        trace_id=trace_id,
        request_id=None,
    )


class TestCapabilityAllowlist:
    """Tests verifying the read-only capability allowlist is complete and correct."""

    def test_read_only_capabilities_are_read_operations(self) -> None:
        """Ensure all read-only capabilities end with read-only verbs."""
        read_verbs = {"read", "search", "fetch", "propose"}
        for cap in READ_ONLY_CAPABILITIES:
            verb = cap.split(".")[-1]
            assert verb in read_verbs, f"Capability '{cap}' has non-read verb '{verb}'"

    def test_side_effecting_capabilities_are_write_operations(self) -> None:
        """Ensure all side-effecting capabilities are write/mutate operations."""
        write_verbs = {"write", "send", "notify", "store", "normalize", "promote", "emit"}
        for cap in SIDE_EFFECTING_CAPABILITIES:
            verb = cap.split(".")[-1]
            assert verb in write_verbs, f"Capability '{cap}' has non-write verb '{verb}'"

    def test_no_overlap_between_allowlist_and_denylist(self) -> None:
        """Ensure allowlist and denylist have no overlapping capabilities."""
        overlap = READ_ONLY_CAPABILITIES & SIDE_EFFECTING_CAPABILITIES
        assert not overlap, f"Overlapping capabilities: {overlap}"

    def test_all_expected_read_capabilities_present(self) -> None:
        """Verify all expected read-only capabilities are in the allowlist."""
        expected = {
            "obsidian.read",
            "memory.propose",
            "vault.search",
            "messaging.read",
            "calendar.read",
            "reminders.read",
            "blob.read",
            "filesystem.read",
            "github.read",
            "web.fetch",
            "scheduler.read",
            "policy.read",
        }
        assert expected <= READ_ONLY_CAPABILITIES, f"Missing: {expected - READ_ONLY_CAPABILITIES}"

    def test_all_expected_write_capabilities_present(self) -> None:
        """Verify all expected side-effecting capabilities are in the denylist."""
        expected = {
            "obsidian.write",
            "memory.promote",
            "messaging.send",
            "attention.notify",
            "calendar.write",
            "reminders.write",
            "blob.store",
            "filesystem.write",
            "github.write",
            "scheduler.write",
            "policy.write",
            "telemetry.emit",
        }
        assert (
            expected <= SIDE_EFFECTING_CAPABILITIES
        ), f"Missing: {expected - SIDE_EFFECTING_CAPABILITIES}"


class TestCapabilityGateAllowed:
    """Tests verifying read-only capabilities are allowed."""

    @pytest.mark.parametrize("capability_id", list(READ_ONLY_CAPABILITIES))
    def test_read_only_capabilities_allowed(self, capability_id: str) -> None:
        """Verify each read-only capability is allowed."""
        gate = CapabilityGate()
        context = _make_valid_actor_context()

        result = gate.check_capability(capability_id, context)

        assert result.decision == CapabilityDecision.ALLOW
        assert result.capability_id == capability_id
        assert result.reason_code is None
        assert result.reason_message is None

    def test_require_capability_does_not_raise_for_read_only(self) -> None:
        """Verify require_capability does not raise for allowed capabilities."""
        gate = CapabilityGate()
        context = _make_valid_actor_context()

        # Should not raise
        gate.require_capability("obsidian.read", context)

    def test_is_read_only_returns_true_for_allowlist(self) -> None:
        """Verify is_read_only returns True for allowed capabilities."""
        gate = CapabilityGate()

        for cap in READ_ONLY_CAPABILITIES:
            assert gate.is_read_only(cap) is True

    def test_is_read_only_returns_false_for_side_effecting(self) -> None:
        """Verify is_read_only returns False for side-effecting capabilities."""
        gate = CapabilityGate()

        for cap in SIDE_EFFECTING_CAPABILITIES:
            assert gate.is_read_only(cap) is False


class TestCapabilityGateDenied:
    """Tests verifying side-effecting capabilities are denied."""

    @pytest.mark.parametrize("capability_id", list(SIDE_EFFECTING_CAPABILITIES))
    def test_side_effecting_capabilities_denied(self, capability_id: str) -> None:
        """Verify each side-effecting capability is denied."""
        gate = CapabilityGate()
        context = _make_valid_actor_context()

        result = gate.check_capability(capability_id, context)

        assert result.decision == CapabilityDecision.DENY
        assert result.capability_id == capability_id
        assert result.reason_code == DenialReasonCode.NOT_READ_ONLY.value
        assert "side-effecting" in (result.reason_message or "")

    def test_unknown_capability_denied(self) -> None:
        """Verify unknown capabilities are denied."""
        gate = CapabilityGate()
        context = _make_valid_actor_context()

        result = gate.check_capability("unknown.capability", context)

        assert result.decision == CapabilityDecision.DENY
        assert result.capability_id == "unknown.capability"
        assert result.reason_code == DenialReasonCode.UNKNOWN_CAPABILITY.value
        assert "not in the read-only allowlist" in (result.reason_message or "")

    def test_require_capability_raises_for_side_effecting(self) -> None:
        """Verify require_capability raises for denied capabilities."""
        gate = CapabilityGate()
        context = _make_valid_actor_context()

        with pytest.raises(CapabilityGateError) as exc_info:
            gate.require_capability("obsidian.write", context)

        assert exc_info.value.code == DenialReasonCode.NOT_READ_ONLY.value
        assert exc_info.value.capability_id == "obsidian.write"
        assert "side-effecting" in str(exc_info.value)

    def test_require_capability_raises_for_unknown(self) -> None:
        """Verify require_capability raises for unknown capabilities."""
        gate = CapabilityGate()
        context = _make_valid_actor_context()

        with pytest.raises(CapabilityGateError) as exc_info:
            gate.require_capability("custom.unknown", context)

        assert exc_info.value.code == DenialReasonCode.UNKNOWN_CAPABILITY.value
        assert exc_info.value.capability_id == "custom.unknown"

    def test_is_side_effecting_returns_true_for_denylist(self) -> None:
        """Verify is_side_effecting returns True for side-effecting capabilities."""
        gate = CapabilityGate()

        for cap in SIDE_EFFECTING_CAPABILITIES:
            assert gate.is_side_effecting(cap) is True

    def test_is_side_effecting_returns_false_for_read_only(self) -> None:
        """Verify is_side_effecting returns False for read-only capabilities."""
        gate = CapabilityGate()

        for cap in READ_ONLY_CAPABILITIES:
            assert gate.is_side_effecting(cap) is False


class TestActorContextValidation:
    """Tests verifying actor context validation for predicate evaluation."""

    def test_invalid_actor_type_denied(self) -> None:
        """Verify non-scheduled actor types are denied."""
        gate = CapabilityGate()
        context = _make_invalid_actor_context(
            actor_type="user",
            channel=SCHEDULED_CHANNEL,
            privilege_level=SCHEDULED_PRIVILEGE_LEVEL,
            autonomy_level=SCHEDULED_AUTONOMY_LEVEL,
        )

        result = gate.check_capability("obsidian.read", context)

        assert result.decision == CapabilityDecision.DENY
        assert result.reason_code == DenialReasonCode.INVALID_ACTOR_CONTEXT.value
        assert "Actor type must be 'scheduled'" in (result.reason_message or "")

    def test_invalid_channel_denied(self) -> None:
        """Verify non-scheduled channels are denied."""
        gate = CapabilityGate()
        context = CapabilityAuthorizationContext(
            actor_type=SCHEDULED_ACTOR_TYPE,
            actor_id=None,
            channel="api",
            privilege_level=SCHEDULED_PRIVILEGE_LEVEL,
            autonomy_level=SCHEDULED_AUTONOMY_LEVEL,
            trace_id="test-trace",
        )

        result = gate.check_capability("obsidian.read", context)

        assert result.decision == CapabilityDecision.DENY
        assert result.reason_code == DenialReasonCode.INVALID_ACTOR_CONTEXT.value
        assert "Channel must be 'scheduled'" in (result.reason_message or "")

    def test_invalid_privilege_level_denied(self) -> None:
        """Verify non-constrained privilege levels are denied."""
        gate = CapabilityGate()
        context = CapabilityAuthorizationContext(
            actor_type=SCHEDULED_ACTOR_TYPE,
            actor_id=None,
            channel=SCHEDULED_CHANNEL,
            privilege_level="elevated",
            autonomy_level=SCHEDULED_AUTONOMY_LEVEL,
            trace_id="test-trace",
        )

        result = gate.check_capability("obsidian.read", context)

        assert result.decision == CapabilityDecision.DENY
        assert result.reason_code == DenialReasonCode.INVALID_ACTOR_CONTEXT.value
        assert "Privilege level must be 'constrained'" in (result.reason_message or "")

    def test_invalid_autonomy_level_denied(self) -> None:
        """Verify non-limited autonomy levels are denied."""
        gate = CapabilityGate()
        context = CapabilityAuthorizationContext(
            actor_type=SCHEDULED_ACTOR_TYPE,
            actor_id=None,
            channel=SCHEDULED_CHANNEL,
            privilege_level=SCHEDULED_PRIVILEGE_LEVEL,
            autonomy_level="full",
            trace_id="test-trace",
        )

        result = gate.check_capability("obsidian.read", context)

        assert result.decision == CapabilityDecision.DENY
        assert result.reason_code == DenialReasonCode.INVALID_ACTOR_CONTEXT.value
        assert "Autonomy level must be 'limited'" in (result.reason_message or "")


class TestAuditRecording:
    """Tests verifying denial attempts are recorded for audit."""

    def test_denial_calls_audit_recorder(self) -> None:
        """Verify denied capability calls the audit recorder."""
        audit_records: list[CapabilityDenialAuditRecord] = []

        def recorder(record: CapabilityDenialAuditRecord) -> None:
            audit_records.append(record)

        gate = CapabilityGate(audit_recorder=recorder)
        context = _make_valid_actor_context(trace_id="audit-trace-001")

        gate.check_capability("obsidian.write", context)

        assert len(audit_records) == 1
        record = audit_records[0]
        assert record.capability_id == "obsidian.write"
        assert record.decision == CapabilityDecision.DENY
        assert record.reason_code == DenialReasonCode.NOT_READ_ONLY.value
        assert record.trace_id == "audit-trace-001"
        assert record.actor_type == SCHEDULED_ACTOR_TYPE

    def test_denial_includes_evaluation_context(self) -> None:
        """Verify evaluation context is included in audit records."""
        audit_records: list[CapabilityDenialAuditRecord] = []

        def recorder(record: CapabilityDenialAuditRecord) -> None:
            audit_records.append(record)

        gate = CapabilityGate(audit_recorder=recorder)
        context = _make_valid_actor_context()

        gate.check_capability(
            "obsidian.write",
            context,
            evaluation_context="schedule_id=42,predicate=status.check",
        )

        assert len(audit_records) == 1
        assert audit_records[0].evaluation_context == "schedule_id=42,predicate=status.check"

    def test_denied_at_timestamp_from_now_provider(self) -> None:
        """Verify denied_at uses the now_provider."""
        audit_records: list[CapabilityDenialAuditRecord] = []
        fixed_time = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        def recorder(record: CapabilityDenialAuditRecord) -> None:
            audit_records.append(record)

        gate = CapabilityGate(
            audit_recorder=recorder,
            now_provider=lambda: fixed_time,
        )
        context = _make_valid_actor_context()

        gate.check_capability("obsidian.write", context)

        assert len(audit_records) == 1
        assert audit_records[0].denied_at == fixed_time

    def test_invalid_actor_context_denial_recorded(self) -> None:
        """Verify invalid actor context denials are recorded."""
        audit_records: list[CapabilityDenialAuditRecord] = []

        def recorder(record: CapabilityDenialAuditRecord) -> None:
            audit_records.append(record)

        gate = CapabilityGate(audit_recorder=recorder)
        context = _make_invalid_actor_context(actor_type="user")

        gate.check_capability("obsidian.read", context)

        assert len(audit_records) == 1
        assert audit_records[0].reason_code == DenialReasonCode.INVALID_ACTOR_CONTEXT.value

    def test_unknown_capability_denial_recorded(self) -> None:
        """Verify unknown capability denials are recorded."""
        audit_records: list[CapabilityDenialAuditRecord] = []

        def recorder(record: CapabilityDenialAuditRecord) -> None:
            audit_records.append(record)

        gate = CapabilityGate(audit_recorder=recorder)
        context = _make_valid_actor_context()

        gate.check_capability("foo.bar", context)

        assert len(audit_records) == 1
        assert audit_records[0].reason_code == DenialReasonCode.UNKNOWN_CAPABILITY.value
        assert audit_records[0].capability_id == "foo.bar"

    def test_allowed_capability_does_not_record(self) -> None:
        """Verify allowed capabilities do not generate audit records."""
        audit_records: list[CapabilityDenialAuditRecord] = []

        def recorder(record: CapabilityDenialAuditRecord) -> None:
            audit_records.append(record)

        gate = CapabilityGate(audit_recorder=recorder)
        context = _make_valid_actor_context()

        gate.check_capability("obsidian.read", context)

        assert len(audit_records) == 0

    def test_audit_recorder_exception_does_not_raise(self) -> None:
        """Verify audit recorder exceptions are caught and logged."""

        def failing_recorder(record: CapabilityDenialAuditRecord) -> None:
            raise RuntimeError("Recorder failed")

        gate = CapabilityGate(audit_recorder=failing_recorder)
        context = _make_valid_actor_context()

        # Should not raise, just log
        result = gate.check_capability("obsidian.write", context)

        assert result.decision == CapabilityDecision.DENY

    def test_require_capability_also_records_denial(self) -> None:
        """Verify require_capability denial is also recorded."""
        audit_records: list[CapabilityDenialAuditRecord] = []

        def recorder(record: CapabilityDenialAuditRecord) -> None:
            audit_records.append(record)

        gate = CapabilityGate(audit_recorder=recorder)
        context = _make_valid_actor_context()

        with pytest.raises(CapabilityGateError):
            gate.require_capability("messaging.send", context)

        assert len(audit_records) == 1
        assert audit_records[0].capability_id == "messaging.send"


class TestCapabilityGateErrorDetails:
    """Tests verifying CapabilityGateError contains useful details."""

    def test_error_includes_capability_id(self) -> None:
        """Verify error includes the denied capability ID."""
        gate = CapabilityGate()
        context = _make_valid_actor_context()

        with pytest.raises(CapabilityGateError) as exc_info:
            gate.require_capability("calendar.write", context)

        assert exc_info.value.capability_id == "calendar.write"

    def test_error_includes_code(self) -> None:
        """Verify error includes a machine-readable code."""
        gate = CapabilityGate()
        context = _make_valid_actor_context()

        with pytest.raises(CapabilityGateError) as exc_info:
            gate.require_capability("calendar.write", context)

        assert exc_info.value.code == DenialReasonCode.NOT_READ_ONLY.value

    def test_error_includes_actor_details(self) -> None:
        """Verify error details include actor context information."""
        gate = CapabilityGate()
        context = _make_valid_actor_context(trace_id="error-trace-123")

        with pytest.raises(CapabilityGateError) as exc_info:
            gate.require_capability("calendar.write", context)

        assert exc_info.value.details["actor_type"] == SCHEDULED_ACTOR_TYPE
        assert exc_info.value.details["channel"] == SCHEDULED_CHANNEL
        assert exc_info.value.details["trace_id"] == "error-trace-123"


class TestCreatePredicateEvaluationActorContext:
    """Tests for the actor context factory function."""

    def test_creates_context_from_scheduled_actor(self) -> None:
        """Verify factory creates context from ScheduledActorContext."""
        scheduled = ScheduledActorContext()
        context = create_predicate_evaluation_actor_context(
            scheduled,
            trace_id="factory-trace-001",
        )

        assert context.actor_type == SCHEDULED_ACTOR_TYPE
        assert context.channel == SCHEDULED_CHANNEL
        assert context.privilege_level == SCHEDULED_PRIVILEGE_LEVEL
        assert context.autonomy_level == SCHEDULED_AUTONOMY_LEVEL
        assert context.trace_id == "factory-trace-001"
        assert context.actor_id is None
        assert context.request_id is None

    def test_creates_context_with_optional_fields(self) -> None:
        """Verify factory accepts optional actor_id and request_id."""
        scheduled = ScheduledActorContext()
        context = create_predicate_evaluation_actor_context(
            scheduled,
            trace_id="factory-trace-002",
            actor_id="schedule-456",
            request_id="req-789",
        )

        assert context.actor_id == "schedule-456"
        assert context.request_id == "req-789"

    def test_created_context_passes_capability_check(self) -> None:
        """Verify created context passes capability checks for read-only ops."""
        scheduled = ScheduledActorContext()
        context = create_predicate_evaluation_actor_context(
            scheduled,
            trace_id="factory-trace-003",
        )
        gate = CapabilityGate()

        result = gate.check_capability("obsidian.read", context)

        assert result.decision == CapabilityDecision.ALLOW


class TestCustomAllowlist:
    """Tests for custom read-only capability allowlist override."""

    def test_custom_allowlist_restricts_capabilities(self) -> None:
        """Verify custom allowlist can restrict available capabilities."""
        custom_allowlist = frozenset(["obsidian.read", "calendar.read"])
        gate = CapabilityGate(read_only_capabilities=custom_allowlist)
        context = _make_valid_actor_context()

        # Allowed in custom list
        result = gate.check_capability("obsidian.read", context)
        assert result.decision == CapabilityDecision.ALLOW

        # Not in custom list (would be allowed in default)
        result = gate.check_capability("vault.search", context)
        assert result.decision == CapabilityDecision.DENY

    def test_custom_allowlist_expands_capabilities(self) -> None:
        """Verify custom allowlist can add capabilities."""
        custom_allowlist = READ_ONLY_CAPABILITIES | {"custom.readonly"}
        gate = CapabilityGate(read_only_capabilities=custom_allowlist)
        context = _make_valid_actor_context()

        result = gate.check_capability("custom.readonly", context)

        assert result.decision == CapabilityDecision.ALLOW
