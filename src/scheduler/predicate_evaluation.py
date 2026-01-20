"""Predicate evaluation service for conditional schedules.

This module implements the predicate evaluation service that executes conditional
schedule predicates using read-only Skills/Ops under a scheduled actor context.
Evaluation results determine whether a conditional schedule triggers an execution
or defers until the next cadence.
"""

from __future__ import annotations

import logging
import re
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Protocol

from sqlalchemy.orm import Session

from models import Schedule
from scheduler.actor_context import ScheduledActorContext
from scheduler.capability_gate import (
    CapabilityAuthorizationContext,
    CapabilityDecision,
    CapabilityGate,
    CapabilityGateError,
    create_predicate_evaluation_actor_context,
)

logger = logging.getLogger(__name__)


class PredicateEvaluationErrorCode(str, Enum):
    """Machine-readable error codes for predicate evaluation failures."""

    INVALID_PREDICATE = "invalid_predicate"
    SUBJECT_NOT_FOUND = "subject_not_found"
    OPERATOR_NOT_SUPPORTED = "operator_not_supported"
    VALUE_TYPE_MISMATCH = "value_type_mismatch"
    FORBIDDEN = "forbidden"
    EVALUATION_FAILED = "evaluation_failed"
    TIMEOUT = "timeout"
    SCHEDULE_NOT_FOUND = "schedule_not_found"
    SCHEDULE_NOT_CONDITIONAL = "schedule_not_conditional"
    INTERNAL_ERROR = "internal_error"


class PredicateEvaluationStatus(str, Enum):
    """Evaluation result status."""

    TRUE = "true"
    FALSE = "false"
    ERROR = "error"


ALLOWED_OPERATORS = frozenset(["eq", "neq", "gt", "gte", "lt", "lte", "exists", "matches"])
ALLOWED_VALUE_TYPES = frozenset(["string", "number", "boolean", "timestamp"])
# Constrained pattern syntax: only alphanumeric, *, ?, and basic character classes
SAFE_PATTERN_REGEX = re.compile(r"^[\w\s.*?\[\]\-]+$")


class PredicateEvaluationServiceError(Exception):
    """Raised when predicate evaluation encounters an error."""

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        """Initialize the error with a machine-readable code and details."""
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class PredicateDefinition:
    """Predicate definition extracted from a schedule."""

    subject: str
    operator: str
    value: str | None
    value_type: str

    @staticmethod
    def from_schedule(schedule: Schedule) -> PredicateDefinition:
        """Create a PredicateDefinition from a Schedule model."""
        return PredicateDefinition(
            subject=schedule.predicate_subject or "",
            operator=str(schedule.predicate_operator) if schedule.predicate_operator else "",
            value=schedule.predicate_value,
            value_type="string",  # Default to string; can be extended
        )


@dataclass(frozen=True)
class PredicateEvaluationRequest:
    """Request payload for predicate evaluation."""

    evaluation_id: str
    schedule_id: int
    task_intent_id: int
    evaluation_time: datetime
    predicate: PredicateDefinition
    actor_context: CapabilityAuthorizationContext
    provider_name: str
    provider_attempt: int
    trace_id: str


@dataclass(frozen=True)
class PredicateEvaluationError:
    """Error details for failed evaluations."""

    error_code: str
    error_message: str


@dataclass(frozen=True)
class PredicateEvaluationResult:
    """Result envelope for predicate evaluations."""

    status: PredicateEvaluationStatus
    result_code: str
    message: str | None = None
    observed_value: str | None = None
    evaluated_at: datetime | None = None
    error: PredicateEvaluationError | None = None

    @property
    def triggered(self) -> bool:
        """Return True if the predicate evaluation triggered an execution."""
        return self.status == PredicateEvaluationStatus.TRUE


@dataclass(frozen=True)
class PredicateEvaluationAuditInput:
    """Input payload for predicate evaluation audit records."""

    evaluation_id: str
    schedule_id: int
    execution_id: int | None
    task_intent_id: int
    actor_type: str
    actor_id: str | None
    actor_channel: str
    actor_privilege_level: str
    actor_autonomy_level: str
    trace_id: str
    request_id: str | None
    predicate_subject: str
    predicate_operator: str
    predicate_value: str | None
    predicate_value_type: str
    evaluation_time: datetime
    evaluated_at: datetime
    status: str
    result_code: str
    message: str | None
    observed_value: str | None
    error_code: str | None
    error_message: str | None
    authorization_decision: str
    authorization_reason_code: str | None
    authorization_reason_message: str | None
    authorization_policy_name: str | None
    authorization_policy_version: str | None
    provider_name: str
    provider_attempt: int
    correlation_id: str


class SubjectResolver(Protocol):
    """Protocol for resolving predicate subjects to observable values.

    Implementations invoke read-only Skills/Ops to fetch the current value
    of a predicate subject. The resolver must enforce read-only constraints
    and is expected to be capability-gated before invocation.
    """

    def resolve(
        self,
        subject: str,
        actor_context: CapabilityAuthorizationContext,
    ) -> str | int | float | bool | None:
        """Resolve a predicate subject to its current observable value.

        Args:
            subject: The predicate subject identifier (e.g., capability/skill/op ID).
            actor_context: The actor context for authorization checks.

        Returns:
            The resolved value, or None if the subject cannot be resolved.

        Raises:
            PredicateEvaluationServiceError: If resolution fails.
        """
        ...


class PredicateEvaluationAuditRecorder(Protocol):
    """Protocol for recording predicate evaluation audit entries."""

    def record(self, audit_input: PredicateEvaluationAuditInput) -> None:
        """Record a predicate evaluation audit entry.

        Args:
            audit_input: The audit input payload.
        """
        ...


class PredicateEvaluationService:
    """Service for evaluating conditional schedule predicates.

    This service:
    - Loads conditional schedule and predicate definition
    - Enforces read-only capability constraints via the capability gate
    - Invokes the subject resolver to fetch observable values
    - Evaluates predicates against resolved values
    - Returns evaluation results with metadata for audit logging

    Usage:
        service = PredicateEvaluationService(
            session_factory=get_session,
            subject_resolver=my_resolver,
            capability_gate=CapabilityGate(),
        )
        result = service.evaluate(request)
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        subject_resolver: SubjectResolver,
        *,
        capability_gate: CapabilityGate | None = None,
        audit_recorder: PredicateEvaluationAuditRecorder | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the predicate evaluation service.

        Args:
            session_factory: Factory returning SQLAlchemy sessions.
            subject_resolver: Resolver for predicate subjects.
            capability_gate: Gate for read-only capability enforcement.
            audit_recorder: Optional recorder for audit entries.
            now_provider: Optional callable returning current UTC datetime.
        """
        self._session_factory = session_factory
        self._subject_resolver = subject_resolver
        self._capability_gate = capability_gate or CapabilityGate()
        self._audit_recorder = audit_recorder
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def evaluate(self, request: PredicateEvaluationRequest) -> PredicateEvaluationResult:
        """Evaluate a conditional schedule predicate.

        Args:
            request: The evaluation request payload.

        Returns:
            PredicateEvaluationResult with the evaluation outcome.
        """
        evaluated_at = self._now_provider()
        authorization_decision = "allow"
        authorization_reason_code: str | None = None
        authorization_reason_message: str | None = None

        # Validate predicate definition
        validation_error = _validate_predicate(request.predicate)
        if validation_error is not None:
            result = PredicateEvaluationResult(
                status=PredicateEvaluationStatus.ERROR,
                result_code=validation_error.error_code,
                message=validation_error.error_message,
                evaluated_at=evaluated_at,
                error=validation_error,
            )
            self._record_audit(request, result, evaluated_at, "allow", None, None)
            return result

        # Extract capability ID from subject (format: "capability.action" or just the subject)
        capability_id = _extract_capability_id(request.predicate.subject)

        # Enforce read-only capability gate
        try:
            check_result = self._capability_gate.check_capability(
                capability_id,
                request.actor_context,
                evaluation_context=f"schedule_id={request.schedule_id},subject={request.predicate.subject}",
            )
            if check_result.decision == CapabilityDecision.DENY:
                authorization_decision = "deny"
                authorization_reason_code = check_result.reason_code
                authorization_reason_message = check_result.reason_message
                result = PredicateEvaluationResult(
                    status=PredicateEvaluationStatus.ERROR,
                    result_code=PredicateEvaluationErrorCode.FORBIDDEN.value,
                    message=check_result.reason_message,
                    evaluated_at=evaluated_at,
                    error=PredicateEvaluationError(
                        error_code=PredicateEvaluationErrorCode.FORBIDDEN.value,
                        error_message=check_result.reason_message or "Capability denied.",
                    ),
                )
                self._record_audit(
                    request,
                    result,
                    evaluated_at,
                    authorization_decision,
                    authorization_reason_code,
                    authorization_reason_message,
                )
                return result
        except CapabilityGateError as exc:
            authorization_decision = "deny"
            authorization_reason_code = exc.code
            authorization_reason_message = str(exc)
            result = PredicateEvaluationResult(
                status=PredicateEvaluationStatus.ERROR,
                result_code=PredicateEvaluationErrorCode.FORBIDDEN.value,
                message=str(exc),
                evaluated_at=evaluated_at,
                error=PredicateEvaluationError(
                    error_code=PredicateEvaluationErrorCode.FORBIDDEN.value,
                    error_message=str(exc),
                ),
            )
            self._record_audit(
                request,
                result,
                evaluated_at,
                authorization_decision,
                authorization_reason_code,
                authorization_reason_message,
            )
            return result

        # Resolve the predicate subject to an observable value
        try:
            observed_value = self._subject_resolver.resolve(
                request.predicate.subject,
                request.actor_context,
            )
        except PredicateEvaluationServiceError as exc:
            result = PredicateEvaluationResult(
                status=PredicateEvaluationStatus.ERROR,
                result_code=exc.code,
                message=str(exc),
                evaluated_at=evaluated_at,
                error=PredicateEvaluationError(
                    error_code=exc.code,
                    error_message=str(exc),
                ),
            )
            self._record_audit(request, result, evaluated_at, authorization_decision, None, None)
            return result
        except Exception as exc:
            logger.exception(
                "Subject resolution failed: schedule_id=%s, subject=%s",
                request.schedule_id,
                request.predicate.subject,
            )
            result = PredicateEvaluationResult(
                status=PredicateEvaluationStatus.ERROR,
                result_code=PredicateEvaluationErrorCode.EVALUATION_FAILED.value,
                message=f"Subject resolution failed: {exc}",
                evaluated_at=evaluated_at,
                error=PredicateEvaluationError(
                    error_code=PredicateEvaluationErrorCode.EVALUATION_FAILED.value,
                    error_message=str(exc),
                ),
            )
            self._record_audit(request, result, evaluated_at, authorization_decision, None, None)
            return result

        # Evaluate the predicate against the resolved value
        try:
            predicate_result = _evaluate_predicate(
                request.predicate,
                observed_value,
            )
        except PredicateEvaluationServiceError as exc:
            result = PredicateEvaluationResult(
                status=PredicateEvaluationStatus.ERROR,
                result_code=exc.code,
                message=str(exc),
                observed_value=_stringify_value(observed_value),
                evaluated_at=evaluated_at,
                error=PredicateEvaluationError(
                    error_code=exc.code,
                    error_message=str(exc),
                ),
            )
            self._record_audit(request, result, evaluated_at, authorization_decision, None, None)
            return result

        status = (
            PredicateEvaluationStatus.TRUE if predicate_result else PredicateEvaluationStatus.FALSE
        )
        result = PredicateEvaluationResult(
            status=status,
            result_code="evaluated",
            message=f"Predicate evaluated to {status.value}.",
            observed_value=_stringify_value(observed_value),
            evaluated_at=evaluated_at,
        )
        self._record_audit(request, result, evaluated_at, authorization_decision, None, None)
        return result

    def evaluate_schedule(
        self,
        schedule_id: int,
        *,
        evaluation_id: str,
        evaluation_time: datetime,
        provider_name: str,
        provider_attempt: int,
        trace_id: str,
    ) -> PredicateEvaluationResult:
        """Load a schedule and evaluate its predicate.

        This is a convenience method that loads the schedule from the database
        and constructs the evaluation request.

        Args:
            schedule_id: The schedule ID to evaluate.
            evaluation_id: Unique ID for idempotency.
            evaluation_time: The authoritative evaluation timestamp.
            provider_name: The scheduler provider name.
            provider_attempt: The delivery attempt number.
            trace_id: Trace ID for correlation.

        Returns:
            PredicateEvaluationResult with the evaluation outcome.
        """
        evaluated_at = self._now_provider()

        with closing(self._session_factory()) as session:
            schedule = session.query(Schedule).filter(Schedule.id == schedule_id).first()
            if schedule is None:
                return PredicateEvaluationResult(
                    status=PredicateEvaluationStatus.ERROR,
                    result_code=PredicateEvaluationErrorCode.SCHEDULE_NOT_FOUND.value,
                    message=f"Schedule {schedule_id} not found.",
                    evaluated_at=evaluated_at,
                    error=PredicateEvaluationError(
                        error_code=PredicateEvaluationErrorCode.SCHEDULE_NOT_FOUND.value,
                        error_message=f"Schedule {schedule_id} not found.",
                    ),
                )

            schedule_type = str(schedule.schedule_type)
            if schedule_type != "conditional":
                return PredicateEvaluationResult(
                    status=PredicateEvaluationStatus.ERROR,
                    result_code=PredicateEvaluationErrorCode.SCHEDULE_NOT_CONDITIONAL.value,
                    message=f"Schedule {schedule_id} is not a conditional schedule (type: {schedule_type}).",
                    evaluated_at=evaluated_at,
                    error=PredicateEvaluationError(
                        error_code=PredicateEvaluationErrorCode.SCHEDULE_NOT_CONDITIONAL.value,
                        error_message=f"Schedule {schedule_id} is not a conditional schedule.",
                    ),
                )

            predicate = PredicateDefinition.from_schedule(schedule)
            task_intent_id = schedule.task_intent_id

        scheduled_context = ScheduledActorContext()
        actor_context = create_predicate_evaluation_actor_context(
            scheduled_context,
            trace_id,
        )

        request = PredicateEvaluationRequest(
            evaluation_id=evaluation_id,
            schedule_id=schedule_id,
            task_intent_id=task_intent_id,
            evaluation_time=evaluation_time,
            predicate=predicate,
            actor_context=actor_context,
            provider_name=provider_name,
            provider_attempt=provider_attempt,
            trace_id=trace_id,
        )

        return self.evaluate(request)

    def _record_audit(
        self,
        request: PredicateEvaluationRequest,
        result: PredicateEvaluationResult,
        evaluated_at: datetime,
        authorization_decision: str,
        authorization_reason_code: str | None,
        authorization_reason_message: str | None,
    ) -> None:
        """Record an audit entry for the evaluation."""
        if self._audit_recorder is None:
            return

        audit_input = PredicateEvaluationAuditInput(
            evaluation_id=request.evaluation_id,
            schedule_id=request.schedule_id,
            execution_id=None,  # Set by caller if execution is created
            task_intent_id=request.task_intent_id,
            actor_type=request.actor_context.actor_type,
            actor_id=request.actor_context.actor_id,
            actor_channel=request.actor_context.channel,
            actor_privilege_level=request.actor_context.privilege_level,
            actor_autonomy_level=request.actor_context.autonomy_level,
            trace_id=request.trace_id,
            request_id=request.actor_context.request_id,
            predicate_subject=request.predicate.subject,
            predicate_operator=request.predicate.operator,
            predicate_value=request.predicate.value,
            predicate_value_type=request.predicate.value_type,
            evaluation_time=request.evaluation_time,
            evaluated_at=evaluated_at,
            status=result.status.value,
            result_code=result.result_code,
            message=result.message,
            observed_value=result.observed_value,
            error_code=result.error.error_code if result.error else None,
            error_message=result.error.error_message if result.error else None,
            authorization_decision=authorization_decision,
            authorization_reason_code=authorization_reason_code,
            authorization_reason_message=authorization_reason_message,
            authorization_policy_name=None,
            authorization_policy_version=None,
            provider_name=request.provider_name,
            provider_attempt=request.provider_attempt,
            correlation_id=request.trace_id,
        )

        try:
            self._audit_recorder.record(audit_input)
        except Exception:
            logger.exception(
                "Failed to record predicate evaluation audit: evaluation_id=%s, schedule_id=%s",
                request.evaluation_id,
                request.schedule_id,
            )


def _validate_predicate(predicate: PredicateDefinition) -> PredicateEvaluationError | None:
    """Validate predicate definition fields.

    Returns:
        PredicateEvaluationError if validation fails, None otherwise.
    """
    if not predicate.subject.strip():
        return PredicateEvaluationError(
            error_code=PredicateEvaluationErrorCode.INVALID_PREDICATE.value,
            error_message="Predicate subject is required.",
        )

    if not predicate.operator.strip():
        return PredicateEvaluationError(
            error_code=PredicateEvaluationErrorCode.INVALID_PREDICATE.value,
            error_message="Predicate operator is required.",
        )

    if predicate.operator not in ALLOWED_OPERATORS:
        return PredicateEvaluationError(
            error_code=PredicateEvaluationErrorCode.OPERATOR_NOT_SUPPORTED.value,
            error_message=f"Operator '{predicate.operator}' is not supported.",
        )

    # exists operator does not require a value
    if predicate.operator != "exists" and predicate.value is None:
        return PredicateEvaluationError(
            error_code=PredicateEvaluationErrorCode.INVALID_PREDICATE.value,
            error_message=f"Predicate value is required for operator '{predicate.operator}'.",
        )

    # matches operator requires a safe pattern
    if predicate.operator == "matches" and predicate.value is not None:
        if not SAFE_PATTERN_REGEX.match(predicate.value):
            return PredicateEvaluationError(
                error_code=PredicateEvaluationErrorCode.INVALID_PREDICATE.value,
                error_message="Pattern contains disallowed characters. Only alphanumeric, *, ?, [], and - are allowed.",
            )

    return None


def _extract_capability_id(subject: str) -> str:
    """Extract the capability ID from a predicate subject.

    Subjects may include additional path segments (e.g., "obsidian.read/notes/path").
    This extracts the base capability ID (e.g., "obsidian.read").

    Args:
        subject: The full predicate subject.

    Returns:
        The extracted capability ID.
    """
    # Handle path-based subjects
    if "/" in subject:
        return subject.split("/")[0]
    return subject


def _evaluate_predicate(
    predicate: PredicateDefinition,
    observed_value: str | int | float | bool | None,
) -> bool:
    """Evaluate a predicate against an observed value.

    Args:
        predicate: The predicate definition.
        observed_value: The resolved value to evaluate against.

    Returns:
        True if the predicate condition is satisfied.

    Raises:
        PredicateEvaluationServiceError: If evaluation fails.
    """
    operator = predicate.operator

    # exists: check for non-empty value
    if operator == "exists":
        if observed_value is None:
            return False
        if isinstance(observed_value, str):
            return len(observed_value.strip()) > 0
        return True

    # For other operators, we need to compare values
    if observed_value is None:
        return False

    predicate_value = predicate.value
    if predicate_value is None:
        return False

    # Type coercion based on observed value type
    try:
        if isinstance(observed_value, bool):
            expected = predicate_value.lower() in ("true", "1", "yes")
        elif isinstance(observed_value, int):
            expected = int(predicate_value)
        elif isinstance(observed_value, float):
            expected = float(predicate_value)
        else:
            expected = predicate_value
    except (ValueError, AttributeError) as exc:
        raise PredicateEvaluationServiceError(
            code=PredicateEvaluationErrorCode.VALUE_TYPE_MISMATCH.value,
            message=f"Cannot convert predicate value '{predicate_value}' to match observed type: {exc}",
        ) from exc

    if operator == "eq":
        return observed_value == expected
    if operator == "neq":
        return observed_value != expected
    if operator == "gt":
        return _compare(observed_value, expected) > 0
    if operator == "gte":
        return _compare(observed_value, expected) >= 0
    if operator == "lt":
        return _compare(observed_value, expected) < 0
    if operator == "lte":
        return _compare(observed_value, expected) <= 0
    if operator == "matches":
        return _matches(observed_value, predicate_value)

    raise PredicateEvaluationServiceError(
        code=PredicateEvaluationErrorCode.OPERATOR_NOT_SUPPORTED.value,
        message=f"Operator '{operator}' is not implemented.",
    )


def _compare(observed: object, expected: object) -> int:
    """Compare two values for ordering.

    Returns:
        Negative if observed < expected, 0 if equal, positive if observed > expected.

    Raises:
        PredicateEvaluationServiceError: If comparison is not supported.
    """
    if isinstance(observed, (int, float)) and isinstance(expected, (int, float)):
        if observed < expected:
            return -1
        if observed > expected:
            return 1
        return 0

    if isinstance(observed, str) and isinstance(expected, str):
        if observed < expected:
            return -1
        if observed > expected:
            return 1
        return 0

    raise PredicateEvaluationServiceError(
        code=PredicateEvaluationErrorCode.VALUE_TYPE_MISMATCH.value,
        message=f"Cannot compare {type(observed).__name__} with {type(expected).__name__}.",
    )


def _matches(observed: object, pattern: str) -> bool:
    """Match an observed value against a constrained pattern.

    The pattern uses simplified glob-like syntax:
    - * matches any sequence of characters
    - ? matches any single character
    - [abc] matches any character in the brackets

    Args:
        observed: The observed value (will be converted to string).
        pattern: The pattern to match against.

    Returns:
        True if the pattern matches.
    """
    observed_str = str(observed)

    # Convert simplified pattern to regex
    # Escape regex special chars except our glob chars
    regex_pattern = ""
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            regex_pattern += ".*"
        elif char == "?":
            regex_pattern += "."
        elif char == "[":
            # Find the closing bracket
            j = i + 1
            while j < len(pattern) and pattern[j] != "]":
                j += 1
            if j < len(pattern):
                regex_pattern += pattern[i : j + 1]
                i = j
            else:
                regex_pattern += re.escape(char)
        else:
            regex_pattern += re.escape(char)
        i += 1

    try:
        return bool(re.fullmatch(regex_pattern, observed_str))
    except re.error:
        return False


def _stringify_value(value: str | int | float | bool | None) -> str | None:
    """Convert a value to a string for audit logging."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
