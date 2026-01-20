"""Unit tests for predicate evaluation service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from scheduler.actor_context import (
    SCHEDULED_ACTOR_TYPE,
    SCHEDULED_AUTONOMY_LEVEL,
    SCHEDULED_CHANNEL,
    SCHEDULED_PRIVILEGE_LEVEL,
)
from scheduler.capability_gate import (
    CapabilityAuthorizationContext,
    CapabilityGate,
)
from scheduler.predicate_evaluation import (
    ALLOWED_OPERATORS,
    PredicateDefinition,
    PredicateEvaluationAuditInput,
    PredicateEvaluationErrorCode,
    PredicateEvaluationRequest,
    PredicateEvaluationResult,
    PredicateEvaluationService,
    PredicateEvaluationServiceError,
    PredicateEvaluationStatus,
    _evaluate_predicate,
    _extract_capability_id,
    _matches,
    _stringify_value,
    _validate_predicate,
)


def _make_actor_context(
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


def _make_predicate(
    *,
    subject: str = "obsidian.read",
    operator: str = "eq",
    value: str | None = "expected",
    value_type: str = "string",
) -> PredicateDefinition:
    """Create a predicate definition for tests."""
    return PredicateDefinition(
        subject=subject,
        operator=operator,
        value=value,
        value_type=value_type,
    )


def _make_evaluation_request(
    *,
    evaluation_id: str = "eval-001",
    schedule_id: int = 1,
    task_intent_id: int = 1,
    predicate: PredicateDefinition | None = None,
    actor_context: CapabilityAuthorizationContext | None = None,
    evaluation_time: datetime | None = None,
    provider_name: str = "test-provider",
    provider_attempt: int = 1,
    trace_id: str = "test-trace-001",
) -> PredicateEvaluationRequest:
    """Create an evaluation request for tests."""
    return PredicateEvaluationRequest(
        evaluation_id=evaluation_id,
        schedule_id=schedule_id,
        task_intent_id=task_intent_id,
        evaluation_time=evaluation_time or datetime.now(timezone.utc),
        predicate=predicate or _make_predicate(),
        actor_context=actor_context or _make_actor_context(trace_id=trace_id),
        provider_name=provider_name,
        provider_attempt=provider_attempt,
        trace_id=trace_id,
    )


class MockSubjectResolver:
    """Mock subject resolver for testing."""

    def __init__(
        self,
        return_value: Any = None,
        raise_error: Exception | None = None,
    ) -> None:
        """Initialize with a return value or error to raise."""
        self._return_value = return_value
        self._raise_error = raise_error
        self.calls: list[tuple[str, CapabilityAuthorizationContext]] = []

    def resolve(
        self,
        subject: str,
        actor_context: CapabilityAuthorizationContext,
    ) -> str | int | float | bool | None:
        """Resolve a subject to a value."""
        self.calls.append((subject, actor_context))
        if self._raise_error is not None:
            raise self._raise_error
        return self._return_value


class MockAuditRecorder:
    """Mock audit recorder for testing."""

    def __init__(
        self,
        raise_error: Exception | None = None,
    ) -> None:
        """Initialize with an optional error to raise."""
        self._raise_error = raise_error
        self.records: list[PredicateEvaluationAuditInput] = []

    def record(self, audit_input: PredicateEvaluationAuditInput) -> None:
        """Record an audit entry."""
        if self._raise_error is not None:
            raise self._raise_error
        self.records.append(audit_input)


class TestPredicateValidation:
    """Tests for predicate definition validation."""

    def test_valid_predicate_passes(self) -> None:
        """Verify valid predicate passes validation."""
        predicate = _make_predicate(subject="obsidian.read", operator="eq", value="test")

        error = _validate_predicate(predicate)

        assert error is None

    def test_empty_subject_fails(self) -> None:
        """Verify empty subject fails validation."""
        predicate = _make_predicate(subject="", operator="eq", value="test")

        error = _validate_predicate(predicate)

        assert error is not None
        assert error.error_code == PredicateEvaluationErrorCode.INVALID_PREDICATE.value
        assert "subject is required" in error.error_message

    def test_whitespace_subject_fails(self) -> None:
        """Verify whitespace-only subject fails validation."""
        predicate = _make_predicate(subject="   ", operator="eq", value="test")

        error = _validate_predicate(predicate)

        assert error is not None
        assert error.error_code == PredicateEvaluationErrorCode.INVALID_PREDICATE.value

    def test_empty_operator_fails(self) -> None:
        """Verify empty operator fails validation."""
        predicate = _make_predicate(subject="obsidian.read", operator="", value="test")

        error = _validate_predicate(predicate)

        assert error is not None
        assert error.error_code == PredicateEvaluationErrorCode.INVALID_PREDICATE.value
        assert "operator is required" in error.error_message

    def test_unsupported_operator_fails(self) -> None:
        """Verify unsupported operator fails validation."""
        predicate = _make_predicate(subject="obsidian.read", operator="like", value="test")

        error = _validate_predicate(predicate)

        assert error is not None
        assert error.error_code == PredicateEvaluationErrorCode.OPERATOR_NOT_SUPPORTED.value
        assert "'like'" in error.error_message

    @pytest.mark.parametrize("operator", list(ALLOWED_OPERATORS))
    def test_all_allowed_operators_pass(self, operator: str) -> None:
        """Verify all allowed operators pass validation."""
        value = "test" if operator != "exists" else None
        predicate = _make_predicate(subject="obsidian.read", operator=operator, value=value)

        error = _validate_predicate(predicate)

        assert error is None

    def test_null_value_fails_for_comparison_operators(self) -> None:
        """Verify null value fails for operators that require values."""
        predicate = _make_predicate(subject="obsidian.read", operator="eq", value=None)

        error = _validate_predicate(predicate)

        assert error is not None
        assert error.error_code == PredicateEvaluationErrorCode.INVALID_PREDICATE.value
        assert "value is required" in error.error_message

    def test_exists_operator_allows_null_value(self) -> None:
        """Verify exists operator allows null value."""
        predicate = _make_predicate(subject="obsidian.read", operator="exists", value=None)

        error = _validate_predicate(predicate)

        assert error is None

    def test_matches_with_unsafe_pattern_fails(self) -> None:
        """Verify matches operator rejects unsafe patterns."""
        predicate = _make_predicate(
            subject="obsidian.read",
            operator="matches",
            value="test$^()",
        )

        error = _validate_predicate(predicate)

        assert error is not None
        assert error.error_code == PredicateEvaluationErrorCode.INVALID_PREDICATE.value
        assert "disallowed characters" in error.error_message

    def test_matches_with_safe_pattern_passes(self) -> None:
        """Verify matches operator accepts safe patterns."""
        predicate = _make_predicate(
            subject="obsidian.read",
            operator="matches",
            value="test*pattern?[abc]",
        )

        error = _validate_predicate(predicate)

        assert error is None


class TestCapabilityExtraction:
    """Tests for capability ID extraction from subjects."""

    def test_simple_subject_returns_as_is(self) -> None:
        """Verify simple subjects are returned unchanged."""
        assert _extract_capability_id("obsidian.read") == "obsidian.read"

    def test_path_subject_extracts_capability(self) -> None:
        """Verify path-based subjects extract the base capability."""
        assert _extract_capability_id("obsidian.read/notes/path") == "obsidian.read"

    def test_deeply_nested_path_extracts_capability(self) -> None:
        """Verify deeply nested paths extract the base capability."""
        assert _extract_capability_id("filesystem.read/path/to/file.txt") == "filesystem.read"


class TestPredicateEvaluation:
    """Tests for predicate evaluation logic."""

    def test_eq_string_match_returns_true(self) -> None:
        """Verify eq operator returns True on exact string match."""
        predicate = _make_predicate(operator="eq", value="hello")

        result = _evaluate_predicate(predicate, "hello")

        assert result is True

    def test_eq_string_mismatch_returns_false(self) -> None:
        """Verify eq operator returns False on string mismatch."""
        predicate = _make_predicate(operator="eq", value="hello")

        result = _evaluate_predicate(predicate, "world")

        assert result is False

    def test_neq_string_mismatch_returns_true(self) -> None:
        """Verify neq operator returns True on string mismatch."""
        predicate = _make_predicate(operator="neq", value="hello")

        result = _evaluate_predicate(predicate, "world")

        assert result is True

    def test_neq_string_match_returns_false(self) -> None:
        """Verify neq operator returns False on exact string match."""
        predicate = _make_predicate(operator="neq", value="hello")

        result = _evaluate_predicate(predicate, "hello")

        assert result is False

    def test_gt_numeric_greater_returns_true(self) -> None:
        """Verify gt operator returns True when observed > expected."""
        predicate = _make_predicate(operator="gt", value="10")

        result = _evaluate_predicate(predicate, 15)

        assert result is True

    def test_gt_numeric_equal_returns_false(self) -> None:
        """Verify gt operator returns False when observed == expected."""
        predicate = _make_predicate(operator="gt", value="10")

        result = _evaluate_predicate(predicate, 10)

        assert result is False

    def test_gte_numeric_equal_returns_true(self) -> None:
        """Verify gte operator returns True when observed == expected."""
        predicate = _make_predicate(operator="gte", value="10")

        result = _evaluate_predicate(predicate, 10)

        assert result is True

    def test_lt_numeric_less_returns_true(self) -> None:
        """Verify lt operator returns True when observed < expected."""
        predicate = _make_predicate(operator="lt", value="10")

        result = _evaluate_predicate(predicate, 5)

        assert result is True

    def test_lte_numeric_equal_returns_true(self) -> None:
        """Verify lte operator returns True when observed == expected."""
        predicate = _make_predicate(operator="lte", value="10")

        result = _evaluate_predicate(predicate, 10)

        assert result is True

    def test_exists_with_non_empty_value_returns_true(self) -> None:
        """Verify exists operator returns True for non-empty values."""
        predicate = _make_predicate(operator="exists", value=None)

        result = _evaluate_predicate(predicate, "something")

        assert result is True

    def test_exists_with_empty_string_returns_false(self) -> None:
        """Verify exists operator returns False for empty strings."""
        predicate = _make_predicate(operator="exists", value=None)

        result = _evaluate_predicate(predicate, "")

        assert result is False

    def test_exists_with_whitespace_returns_false(self) -> None:
        """Verify exists operator returns False for whitespace-only strings."""
        predicate = _make_predicate(operator="exists", value=None)

        result = _evaluate_predicate(predicate, "   ")

        assert result is False

    def test_exists_with_none_returns_false(self) -> None:
        """Verify exists operator returns False for None."""
        predicate = _make_predicate(operator="exists", value=None)

        result = _evaluate_predicate(predicate, None)

        assert result is False

    def test_exists_with_number_returns_true(self) -> None:
        """Verify exists operator returns True for numbers."""
        predicate = _make_predicate(operator="exists", value=None)

        result = _evaluate_predicate(predicate, 42)

        assert result is True

    def test_exists_with_zero_returns_true(self) -> None:
        """Verify exists operator returns True for zero."""
        predicate = _make_predicate(operator="exists", value=None)

        result = _evaluate_predicate(predicate, 0)

        assert result is True

    def test_exists_with_boolean_false_returns_true(self) -> None:
        """Verify exists operator returns True for boolean False."""
        predicate = _make_predicate(operator="exists", value=None)

        result = _evaluate_predicate(predicate, False)

        assert result is True

    def test_matches_glob_star_returns_true(self) -> None:
        """Verify matches operator handles * wildcard."""
        predicate = _make_predicate(operator="matches", value="test*value")

        result = _evaluate_predicate(predicate, "test123value")

        assert result is True

    def test_matches_glob_question_returns_true(self) -> None:
        """Verify matches operator handles ? wildcard."""
        predicate = _make_predicate(operator="matches", value="test?value")

        result = _evaluate_predicate(predicate, "testXvalue")

        assert result is True

    def test_matches_character_class_returns_true(self) -> None:
        """Verify matches operator handles character classes."""
        predicate = _make_predicate(operator="matches", value="test[abc]value")

        result = _evaluate_predicate(predicate, "testavalue")

        assert result is True

    def test_matches_no_match_returns_false(self) -> None:
        """Verify matches operator returns False on no match."""
        predicate = _make_predicate(operator="matches", value="test*")

        result = _evaluate_predicate(predicate, "nope")

        assert result is False

    def test_eq_boolean_true_match(self) -> None:
        """Verify eq operator handles boolean True matching."""
        predicate = _make_predicate(operator="eq", value="true")

        result = _evaluate_predicate(predicate, True)

        assert result is True

    def test_eq_boolean_false_match(self) -> None:
        """Verify eq operator handles boolean False matching."""
        predicate = _make_predicate(operator="eq", value="false")

        result = _evaluate_predicate(predicate, False)

        assert result is True

    def test_null_observed_returns_false_for_comparison(self) -> None:
        """Verify comparison operators return False for None observed values."""
        predicate = _make_predicate(operator="eq", value="test")

        result = _evaluate_predicate(predicate, None)

        assert result is False

    def test_value_type_mismatch_raises_error(self) -> None:
        """Verify type mismatch raises an error."""
        predicate = _make_predicate(operator="eq", value="not-a-number")

        with pytest.raises(PredicateEvaluationServiceError) as exc_info:
            _evaluate_predicate(predicate, 42)

        assert exc_info.value.code == PredicateEvaluationErrorCode.VALUE_TYPE_MISMATCH.value

    def test_float_comparison(self) -> None:
        """Verify float comparison works correctly."""
        predicate = _make_predicate(operator="gt", value="3.14")

        result = _evaluate_predicate(predicate, 3.15)

        assert result is True


class TestMatchesFunction:
    """Tests for the _matches helper function."""

    def test_exact_match(self) -> None:
        """Verify exact string matching."""
        assert _matches("hello", "hello") is True

    def test_star_matches_any(self) -> None:
        """Verify * matches any sequence."""
        assert _matches("hello world", "hello*") is True
        assert _matches("hello", "hello*") is True
        assert _matches("helloABC", "hello*") is True

    def test_question_matches_single(self) -> None:
        """Verify ? matches exactly one character."""
        assert _matches("cat", "c?t") is True
        assert _matches("caat", "c?t") is False

    def test_character_class(self) -> None:
        """Verify character class matching."""
        assert _matches("cat", "c[aeo]t") is True
        assert _matches("cot", "c[aeo]t") is True
        assert _matches("cut", "c[aeo]t") is False

    def test_converts_non_string_to_string(self) -> None:
        """Verify non-string values are converted."""
        assert _matches(123, "123") is True
        assert _matches(True, "True") is True


class TestStringifyValue:
    """Tests for the _stringify_value helper function."""

    def test_none_returns_none(self) -> None:
        """Verify None returns None."""
        assert _stringify_value(None) is None

    def test_string_returns_as_is(self) -> None:
        """Verify string returns unchanged."""
        assert _stringify_value("hello") == "hello"

    def test_int_returns_string(self) -> None:
        """Verify int returns string representation."""
        assert _stringify_value(42) == "42"

    def test_float_returns_string(self) -> None:
        """Verify float returns string representation."""
        assert _stringify_value(3.14) == "3.14"

    def test_bool_true_returns_lowercase(self) -> None:
        """Verify True returns 'true'."""
        assert _stringify_value(True) == "true"

    def test_bool_false_returns_lowercase(self) -> None:
        """Verify False returns 'false'."""
        assert _stringify_value(False) == "false"


class TestPredicateEvaluationServiceBasic:
    """Tests for basic predicate evaluation service functionality."""

    def _make_service(
        self,
        resolver: MockSubjectResolver | None = None,
        gate: CapabilityGate | None = None,
        audit_recorder: MockAuditRecorder | None = None,
        now: datetime | None = None,
    ) -> PredicateEvaluationService:
        """Create a service with mocked dependencies."""
        return PredicateEvaluationService(
            session_factory=lambda: None,  # type: ignore[return-value]
            subject_resolver=resolver or MockSubjectResolver(return_value="test"),
            capability_gate=gate,
            audit_recorder=audit_recorder,
            now_provider=lambda: now or datetime.now(timezone.utc),
        )

    def test_successful_evaluation_returns_true_status(self) -> None:
        """Verify successful evaluation with matching value returns True status."""
        resolver = MockSubjectResolver(return_value="expected")
        service = self._make_service(resolver=resolver)
        request = _make_evaluation_request(
            predicate=_make_predicate(operator="eq", value="expected"),
        )

        result = service.evaluate(request)

        assert result.status == PredicateEvaluationStatus.TRUE
        assert result.result_code == "evaluated"
        assert result.observed_value == "expected"
        assert result.error is None

    def test_successful_evaluation_returns_false_status(self) -> None:
        """Verify successful evaluation with non-matching value returns False status."""
        resolver = MockSubjectResolver(return_value="actual")
        service = self._make_service(resolver=resolver)
        request = _make_evaluation_request(
            predicate=_make_predicate(operator="eq", value="expected"),
        )

        result = service.evaluate(request)

        assert result.status == PredicateEvaluationStatus.FALSE
        assert result.result_code == "evaluated"
        assert result.observed_value == "actual"

    def test_invalid_predicate_returns_error_status(self) -> None:
        """Verify invalid predicate returns error status."""
        service = self._make_service()
        request = _make_evaluation_request(
            predicate=_make_predicate(subject="", operator="eq", value="test"),
        )

        result = service.evaluate(request)

        assert result.status == PredicateEvaluationStatus.ERROR
        assert result.result_code == PredicateEvaluationErrorCode.INVALID_PREDICATE.value
        assert result.error is not None

    def test_capability_denial_returns_forbidden_error(self) -> None:
        """Verify capability denial returns forbidden error."""
        # Use a gate that will deny based on invalid actor context
        gate = CapabilityGate()
        resolver = MockSubjectResolver(return_value="test")
        service = self._make_service(resolver=resolver, gate=gate)

        # Create actor context with invalid actor type
        invalid_context = CapabilityAuthorizationContext(
            actor_type="user",  # Invalid for predicate evaluation
            actor_id=None,
            channel=SCHEDULED_CHANNEL,
            privilege_level=SCHEDULED_PRIVILEGE_LEVEL,
            autonomy_level=SCHEDULED_AUTONOMY_LEVEL,
            trace_id="test-trace",
        )
        request = _make_evaluation_request(actor_context=invalid_context)

        result = service.evaluate(request)

        assert result.status == PredicateEvaluationStatus.ERROR
        assert result.result_code == PredicateEvaluationErrorCode.FORBIDDEN.value
        assert result.error is not None
        assert resolver.calls == []  # Resolver should not be called

    def test_side_effecting_capability_denied(self) -> None:
        """Verify side-effecting capabilities are denied."""
        gate = CapabilityGate()
        resolver = MockSubjectResolver(return_value="test")
        service = self._make_service(resolver=resolver, gate=gate)
        request = _make_evaluation_request(
            predicate=_make_predicate(subject="obsidian.write"),  # Side-effecting
        )

        result = service.evaluate(request)

        assert result.status == PredicateEvaluationStatus.ERROR
        assert result.result_code == PredicateEvaluationErrorCode.FORBIDDEN.value
        assert resolver.calls == []  # Resolver should not be called

    def test_resolver_error_returns_error_status(self) -> None:
        """Verify resolver errors are handled properly."""
        error = PredicateEvaluationServiceError(
            code=PredicateEvaluationErrorCode.SUBJECT_NOT_FOUND.value,
            message="Subject not found.",
        )
        resolver = MockSubjectResolver(raise_error=error)
        service = self._make_service(resolver=resolver)
        request = _make_evaluation_request()

        result = service.evaluate(request)

        assert result.status == PredicateEvaluationStatus.ERROR
        assert result.result_code == PredicateEvaluationErrorCode.SUBJECT_NOT_FOUND.value
        assert result.error is not None

    def test_resolver_exception_returns_evaluation_failed(self) -> None:
        """Verify generic resolver exceptions return evaluation_failed."""
        resolver = MockSubjectResolver(raise_error=RuntimeError("Unexpected error"))
        service = self._make_service(resolver=resolver)
        request = _make_evaluation_request()

        result = service.evaluate(request)

        assert result.status == PredicateEvaluationStatus.ERROR
        assert result.result_code == PredicateEvaluationErrorCode.EVALUATION_FAILED.value

    def test_resolver_receives_correct_arguments(self) -> None:
        """Verify resolver receives correct subject and actor context."""
        resolver = MockSubjectResolver(return_value="test")
        service = self._make_service(resolver=resolver)
        actor_context = _make_actor_context(trace_id="resolver-trace-001")
        request = _make_evaluation_request(
            predicate=_make_predicate(subject="obsidian.read/notes/test"),
            actor_context=actor_context,
        )

        service.evaluate(request)

        assert len(resolver.calls) == 1
        subject, context = resolver.calls[0]
        assert subject == "obsidian.read/notes/test"
        assert context.trace_id == "resolver-trace-001"


class TestPredicateEvaluationServiceAudit:
    """Tests for predicate evaluation audit recording."""

    def _make_service(
        self,
        resolver: MockSubjectResolver | None = None,
        audit_recorder: MockAuditRecorder | None = None,
        now: datetime | None = None,
    ) -> PredicateEvaluationService:
        """Create a service with mocked dependencies."""
        return PredicateEvaluationService(
            session_factory=lambda: None,  # type: ignore[return-value]
            subject_resolver=resolver or MockSubjectResolver(return_value="test"),
            audit_recorder=audit_recorder,
            now_provider=lambda: now or datetime.now(timezone.utc),
        )

    def test_successful_evaluation_records_audit(self) -> None:
        """Verify successful evaluations record audit entries."""
        recorder = MockAuditRecorder()
        fixed_time = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        resolver = MockSubjectResolver(return_value="expected")
        service = self._make_service(
            resolver=resolver,
            audit_recorder=recorder,
            now=fixed_time,
        )
        request = _make_evaluation_request(
            evaluation_id="audit-eval-001",
            schedule_id=42,
            task_intent_id=10,
            predicate=_make_predicate(
                subject="obsidian.read",
                operator="eq",
                value="expected",
            ),
            trace_id="audit-trace-001",
        )

        service.evaluate(request)

        assert len(recorder.records) == 1
        audit = recorder.records[0]
        assert audit.evaluation_id == "audit-eval-001"
        assert audit.schedule_id == 42
        assert audit.task_intent_id == 10
        assert audit.status == "true"
        assert audit.result_code == "evaluated"
        assert audit.observed_value == "expected"
        assert audit.evaluated_at == fixed_time
        assert audit.trace_id == "audit-trace-001"
        assert audit.authorization_decision == "allow"

    def test_denied_capability_records_audit_with_denial(self) -> None:
        """Verify denied capabilities record audit with denial details."""
        recorder = MockAuditRecorder()
        gate = CapabilityGate()
        service = PredicateEvaluationService(
            session_factory=lambda: None,  # type: ignore[return-value]
            subject_resolver=MockSubjectResolver(return_value="test"),
            capability_gate=gate,
            audit_recorder=recorder,
        )
        request = _make_evaluation_request(
            predicate=_make_predicate(subject="obsidian.write"),
        )

        service.evaluate(request)

        assert len(recorder.records) == 1
        audit = recorder.records[0]
        assert audit.authorization_decision == "deny"
        assert audit.authorization_reason_code is not None
        assert audit.error_code == PredicateEvaluationErrorCode.FORBIDDEN.value

    def test_error_evaluation_records_audit(self) -> None:
        """Verify error evaluations record audit entries."""
        recorder = MockAuditRecorder()
        resolver = MockSubjectResolver(
            raise_error=PredicateEvaluationServiceError(
                code="subject_not_found",
                message="Not found",
            )
        )
        service = self._make_service(resolver=resolver, audit_recorder=recorder)
        request = _make_evaluation_request()

        service.evaluate(request)

        assert len(recorder.records) == 1
        audit = recorder.records[0]
        assert audit.status == "error"
        assert audit.error_code == "subject_not_found"

    def test_audit_recorder_exception_does_not_raise(self) -> None:
        """Verify audit recorder exceptions do not propagate."""
        recorder = MockAuditRecorder(raise_error=RuntimeError("Audit failed"))
        resolver = MockSubjectResolver(return_value="matched")
        service = self._make_service(resolver=resolver, audit_recorder=recorder)
        request = _make_evaluation_request(
            predicate=_make_predicate(operator="eq", value="matched"),
        )

        # Should not raise
        result = service.evaluate(request)

        assert result.status == PredicateEvaluationStatus.TRUE

    def test_no_audit_recorded_when_no_recorder(self) -> None:
        """Verify no audit is recorded when no recorder is configured."""
        resolver = MockSubjectResolver(return_value="matched")
        service = self._make_service(resolver=resolver, audit_recorder=None)
        request = _make_evaluation_request(
            predicate=_make_predicate(operator="eq", value="matched"),
        )

        # Should not raise
        result = service.evaluate(request)

        assert result.status == PredicateEvaluationStatus.TRUE


class TestPredicateEvaluationServiceTriggered:
    """Tests for the triggered property on evaluation results."""

    def test_triggered_true_when_status_true(self) -> None:
        """Verify triggered is True when status is TRUE."""
        result = PredicateEvaluationResult(
            status=PredicateEvaluationStatus.TRUE,
            result_code="evaluated",
        )

        assert result.triggered is True

    def test_triggered_false_when_status_false(self) -> None:
        """Verify triggered is False when status is FALSE."""
        result = PredicateEvaluationResult(
            status=PredicateEvaluationStatus.FALSE,
            result_code="evaluated",
        )

        assert result.triggered is False

    def test_triggered_false_when_status_error(self) -> None:
        """Verify triggered is False when status is ERROR."""
        result = PredicateEvaluationResult(
            status=PredicateEvaluationStatus.ERROR,
            result_code="error",
        )

        assert result.triggered is False


class TestPredicateDefinitionFromSchedule:
    """Tests for PredicateDefinition.from_schedule factory."""

    def test_extracts_predicate_fields(self) -> None:
        """Verify predicate fields are extracted from schedule."""
        from models import Schedule

        schedule = Schedule(
            id=1,
            task_intent_id=1,
            schedule_type="conditional",
            state="active",
            timezone="UTC",
            created_by_actor_type="user",
            predicate_subject="obsidian.read",
            predicate_operator="eq",
            predicate_value="expected",
        )

        predicate = PredicateDefinition.from_schedule(schedule)

        assert predicate.subject == "obsidian.read"
        assert predicate.operator == "eq"
        assert predicate.value == "expected"
        assert predicate.value_type == "string"

    def test_handles_null_predicate_fields(self) -> None:
        """Verify None predicate fields are handled."""
        from models import Schedule

        schedule = Schedule(
            id=1,
            task_intent_id=1,
            schedule_type="conditional",
            state="active",
            timezone="UTC",
            created_by_actor_type="user",
            predicate_subject=None,
            predicate_operator=None,
            predicate_value=None,
        )

        predicate = PredicateDefinition.from_schedule(schedule)

        assert predicate.subject == ""
        assert predicate.operator == ""
        assert predicate.value is None
