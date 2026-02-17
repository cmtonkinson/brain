"""Predicate evaluation audit recording implementation.

This module provides the concrete implementation of the PredicateEvaluationAuditRecorder
protocol, persisting audit records for predicate evaluation outcomes to the database.
"""

from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy.orm import Session

from scheduler.data_access import (
    PredicateEvaluationAuditInput as DataAccessAuditInput,
    record_predicate_evaluation_audit,
)
from scheduler.predicate_evaluation import PredicateEvaluationAuditInput

logger = logging.getLogger(__name__)


class PredicateEvaluationAuditRecorder:
    """Concrete implementation of audit recording for predicate evaluations.

    This recorder persists audit records to the PredicateEvaluationAuditLog table
    using the data access layer. It implements idempotency through the unique
    evaluation_id constraint.

    Usage:
        recorder = PredicateEvaluationAuditRecorder(session_factory=get_session)
        service = PredicateEvaluationService(
            session_factory=get_session,
            subject_resolver=resolver,
            audit_recorder=recorder,
        )
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the audit recorder.

        Args:
            session_factory: Factory returning SQLAlchemy sessions.
        """
        self._session_factory = session_factory

    def record(self, audit_input: PredicateEvaluationAuditInput) -> None:
        """Record a predicate evaluation audit entry.

        Converts the service-layer PredicateEvaluationAuditInput to the data access
        layer input format and persists the record. Idempotency is handled by the
        data access layer using the unique evaluation_id.

        Args:
            audit_input: The audit input payload from the evaluation service.

        Raises:
            Exception: Propagates database errors to caller. The caller is expected
                to handle exceptions appropriately (typically by logging and
                continuing, since audit failures should not affect evaluation results).
        """
        session = self._session_factory()
        try:
            # Convert from service-layer input to data access layer input
            da_input = DataAccessAuditInput(
                evaluation_id=audit_input.evaluation_id,
                schedule_id=audit_input.schedule_id,
                execution_id=audit_input.execution_id,
                task_intent_id=audit_input.task_intent_id,
                actor_type=audit_input.actor_type,
                actor_id=audit_input.actor_id,
                actor_channel=audit_input.actor_channel,
                actor_privilege_level=audit_input.actor_privilege_level,
                actor_autonomy_level=audit_input.actor_autonomy_level,
                trace_id=audit_input.trace_id,
                request_id=audit_input.request_id,
                predicate_subject=audit_input.predicate_subject,
                predicate_operator=audit_input.predicate_operator,
                predicate_value=audit_input.predicate_value,
                predicate_value_type=audit_input.predicate_value_type,
                evaluation_time=audit_input.evaluation_time,
                evaluated_at=audit_input.evaluated_at,
                status=audit_input.status,
                result_code=audit_input.result_code,
                message=audit_input.message,
                observed_value=audit_input.observed_value,
                error_code=audit_input.error_code,
                error_message=audit_input.error_message,
                authorization_decision=audit_input.authorization_decision,
                authorization_reason_code=audit_input.authorization_reason_code,
                authorization_reason_message=audit_input.authorization_reason_message,
                authorization_policy_name=audit_input.authorization_policy_name,
                authorization_policy_version=audit_input.authorization_policy_version,
                provider_name=audit_input.provider_name,
                provider_attempt=audit_input.provider_attempt,
                correlation_id=audit_input.correlation_id,
            )
            record_predicate_evaluation_audit(session, da_input)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
