"""Authoritative Postgres repository for Job Service state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from packages.brain_shared.ids import (
    generate_ulid_bytes,
    ulid_bytes_to_str,
    ulid_str_to_bytes,
)
from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
from services.control.job.domain import (
    BackoffStrategy,
    ExecutionAudit,
    ExecutionRecord,
    ExecutionStatus,
    JobIntent,
    JobMutationAudit,
    JobRecord,
    JobState,
    PredicateEvaluationStatus,
    PredicateEvaluationRecord,
    job_action_adapter,
    schedule_definition_adapter,
)

from .schema import (
    execution_audits,
    executions,
    job_intents,
    job_mutation_audits,
    jobs,
    predicate_evaluations,
    review_items,
    review_outputs,
)


class PostgresJobRepository:
    """SQL repository over Job Service-owned schema tables."""

    def __init__(self, sessions: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions

    # ------------------------------------------------------------------
    # Job intents
    # ------------------------------------------------------------------

    def create_job_intent(
        self,
        *,
        summary: str,
        action_kind: str,
        capability_id: str,
        input_payload_json: dict[str, object],
        details: str | None,
        origin_reference: str | None,
        created_by_actor: str,
        created_at: datetime,
    ) -> JobIntent:
        """Persist one job intent."""
        row_id = generate_ulid_bytes()
        with self._sessions.session() as session:
            session.execute(
                job_intents.insert().values(
                    id=row_id,
                    summary=summary,
                    action_kind=action_kind,
                    capability_id=capability_id,
                    input_payload=input_payload_json,
                    details=details,
                    origin_reference=origin_reference,
                    created_by_actor=created_by_actor,
                    created_at=created_at,
                )
            )
            row = (
                session.execute(select(job_intents).where(job_intents.c.id == row_id))
                .mappings()
                .one()
            )
            return _to_job_intent(row)

    def get_job_intent(self, *, job_intent_id: str) -> JobIntent | None:
        """Read one job intent by id."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(job_intents).where(
                        job_intents.c.id == ulid_str_to_bytes(job_intent_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_job_intent(row)

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    def create_job(
        self,
        *,
        job_intent_id: str,
        schedule_type: str,
        state: str,
        timezone: str,
        definition_json: dict[str, object],
        next_run_at: datetime | None,
        retry_max_attempts: int,
        retry_backoff_strategy: str,
        retry_backoff_base_seconds: int,
        origin_trace_id: str,
        origin_envelope_id: str,
        created_at: datetime,
    ) -> JobRecord:
        """Persist one job record."""
        row_id = generate_ulid_bytes()
        with self._sessions.session() as session:
            session.execute(
                jobs.insert().values(
                    id=row_id,
                    job_intent_id=ulid_str_to_bytes(job_intent_id),
                    schedule_type=schedule_type,
                    state=state,
                    timezone=timezone,
                    definition=definition_json,
                    next_run_at=next_run_at,
                    retry_max_attempts=retry_max_attempts,
                    retry_backoff_strategy=retry_backoff_strategy,
                    retry_backoff_base_seconds=retry_backoff_base_seconds,
                    origin_trace_id=origin_trace_id,
                    origin_envelope_id=origin_envelope_id,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            row = (
                session.execute(select(jobs).where(jobs.c.id == row_id))
                .mappings()
                .one()
            )
            return _to_job_record(row)

    def get_job(self, *, job_id: str) -> JobRecord | None:
        """Read one job by id."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(jobs).where(jobs.c.id == ulid_str_to_bytes(job_id))
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_job_record(row)

    def list_jobs(
        self,
        *,
        state: str | None,
        schedule_type: str | None,
        limit: int,
        cursor: str | None,
    ) -> list[JobRecord]:
        """List jobs with optional filters and cursor pagination."""
        with self._sessions.session() as session:
            stmt = select(jobs).order_by(jobs.c.id)
            if state is not None:
                stmt = stmt.where(jobs.c.state == state)
            if schedule_type is not None:
                stmt = stmt.where(jobs.c.schedule_type == schedule_type)
            if cursor is not None:
                stmt = stmt.where(jobs.c.id > ulid_str_to_bytes(cursor))
            stmt = stmt.limit(limit)
            rows = session.execute(stmt).mappings().all()
            return [_to_job_record(r) for r in rows]

    def update_job(
        self,
        *,
        job_id: str,
        timezone: str | None,
        definition_json: dict[str, object] | None,
        next_run_at: datetime | None,
        updated_at: datetime,
    ) -> JobRecord | None:
        """Update job definition, timezone, and/or next_run."""
        values: dict[str, object] = {"updated_at": updated_at}
        if timezone is not None:
            values["timezone"] = timezone
        if definition_json is not None:
            values["definition"] = definition_json
        values["next_run_at"] = next_run_at

        job_id_bytes = ulid_str_to_bytes(job_id)
        with self._sessions.session() as session:
            session.execute(
                update(jobs).where(jobs.c.id == job_id_bytes).values(**values)
            )
            row = (
                session.execute(select(jobs).where(jobs.c.id == job_id_bytes))
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_job_record(row)

    def update_job_state(
        self,
        *,
        job_id: str,
        state: str,
        next_run_at: datetime | None,
        updated_at: datetime,
    ) -> JobRecord | None:
        """Update job state and optionally next_run_at."""
        job_id_bytes = ulid_str_to_bytes(job_id)
        with self._sessions.session() as session:
            session.execute(
                update(jobs)
                .where(jobs.c.id == job_id_bytes)
                .values(
                    state=state,
                    next_run_at=next_run_at,
                    updated_at=updated_at,
                )
            )
            row = (
                session.execute(select(jobs).where(jobs.c.id == job_id_bytes))
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_job_record(row)

    def update_job_run_state(
        self,
        *,
        job_id: str,
        last_run_at: datetime,
        last_run_status: str,
        failure_count: int,
        last_error_message: str | None,
        next_run_at: datetime | None,
        state: str | None,
        updated_at: datetime,
    ) -> JobRecord | None:
        """Update job run-state fields after execution completes."""
        values: dict[str, object] = {
            "last_run_at": last_run_at,
            "last_run_status": last_run_status,
            "failure_count": failure_count,
            "last_error_message": last_error_message,
            "next_run_at": next_run_at,
            "updated_at": updated_at,
        }
        if state is not None:
            values["state"] = state

        job_id_bytes = ulid_str_to_bytes(job_id)
        with self._sessions.session() as session:
            session.execute(
                update(jobs).where(jobs.c.id == job_id_bytes).values(**values)
            )
            row = (
                session.execute(select(jobs).where(jobs.c.id == job_id_bytes))
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_job_record(row)

    # ------------------------------------------------------------------
    # Executions
    # ------------------------------------------------------------------

    def create_execution(
        self,
        *,
        job_id: str,
        job_intent_id: str,
        scheduled_for: datetime,
        status: str,
        attempt_number: int,
        max_attempts: int,
        retry_backoff_strategy: str | None,
        trace_id: str,
        parent_envelope_id: str,
        trigger_source: str,
        created_at: datetime,
    ) -> ExecutionRecord:
        """Persist one execution record."""
        row_id = generate_ulid_bytes()
        with self._sessions.session() as session:
            session.execute(
                executions.insert().values(
                    id=row_id,
                    job_id=ulid_str_to_bytes(job_id),
                    job_intent_id=ulid_str_to_bytes(job_intent_id),
                    scheduled_for=scheduled_for,
                    status=status,
                    attempt_number=attempt_number,
                    max_attempts=max_attempts,
                    retry_backoff_strategy=retry_backoff_strategy,
                    trace_id=trace_id,
                    parent_envelope_id=parent_envelope_id,
                    trigger_source=trigger_source,
                    created_at=created_at,
                )
            )
            row = (
                session.execute(select(executions).where(executions.c.id == row_id))
                .mappings()
                .one()
            )
            return _to_execution_record(row)

    def get_execution(self, *, execution_id: str) -> ExecutionRecord | None:
        """Read one execution by id."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(executions).where(
                        executions.c.id == ulid_str_to_bytes(execution_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_execution_record(row)

    def get_execution_by_job_and_trace(
        self, *, job_id: str, trace_id: str
    ) -> ExecutionRecord | None:
        """Read one execution by (job_id, trace_id) for idempotency checks."""
        with self._sessions.session() as session:
            row = (
                session.execute(
                    select(executions).where(
                        executions.c.job_id == ulid_str_to_bytes(job_id),
                        executions.c.trace_id == trace_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_execution_record(row)

    def update_execution_status(
        self,
        *,
        execution_id: str,
        status: str,
        started_at: datetime | None,
        finished_at: datetime | None,
        retry_after: datetime | None,
        error_message: str | None,
        error_code: str | None,
        attempt_number: int | None,
    ) -> ExecutionRecord | None:
        """Update execution status and related fields."""
        values: dict[str, object] = {
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "retry_after": retry_after,
            "error_message": error_message,
            "error_code": error_code,
        }
        if attempt_number is not None:
            values["attempt_number"] = attempt_number

        exec_id_bytes = ulid_str_to_bytes(execution_id)
        with self._sessions.session() as session:
            session.execute(
                update(executions)
                .where(executions.c.id == exec_id_bytes)
                .values(**values)
            )
            row = (
                session.execute(
                    select(executions).where(executions.c.id == exec_id_bytes)
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _to_execution_record(row)

    def list_executions(
        self,
        *,
        job_id: str,
        limit: int,
        cursor: str | None,
    ) -> list[ExecutionRecord]:
        """List executions for one job with cursor pagination."""
        with self._sessions.session() as session:
            stmt = (
                select(executions)
                .where(executions.c.job_id == ulid_str_to_bytes(job_id))
                .order_by(executions.c.id)
            )
            if cursor is not None:
                stmt = stmt.where(executions.c.id > ulid_str_to_bytes(cursor))
            stmt = stmt.limit(limit)
            rows = session.execute(stmt).mappings().all()
            return [_to_execution_record(r) for r in rows]

    def list_retry_due_executions(self, *, now: datetime) -> list[ExecutionRecord]:
        """List executions with status retry_scheduled and retry_after <= now."""
        with self._sessions.session() as session:
            stmt = (
                select(executions)
                .where(
                    executions.c.status == ExecutionStatus.retry_scheduled.value,
                    executions.c.retry_after <= now,
                )
                .order_by(executions.c.retry_after)
            )
            rows = session.execute(stmt).mappings().all()
            return [_to_execution_record(r) for r in rows]

    # ------------------------------------------------------------------
    # Audits
    # ------------------------------------------------------------------

    def create_job_mutation_audit(
        self,
        *,
        job_id: str,
        event_type: str,
        actor_type: str,
        actor_id: str | None,
        channel: str,
        trace_id: str,
        diff_summary: str | None,
        notes: str | None,
        created_at: datetime,
    ) -> JobMutationAudit:
        """Persist one job mutation audit entry."""
        row_id = generate_ulid_bytes()
        with self._sessions.session() as session:
            session.execute(
                job_mutation_audits.insert().values(
                    id=row_id,
                    job_id=ulid_str_to_bytes(job_id),
                    event_type=event_type,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    channel=channel,
                    trace_id=trace_id,
                    diff_summary=diff_summary,
                    notes=notes,
                    created_at=created_at,
                )
            )
            row = (
                session.execute(
                    select(job_mutation_audits).where(
                        job_mutation_audits.c.id == row_id
                    )
                )
                .mappings()
                .one()
            )
            return _to_job_mutation_audit(row)

    def list_job_audits(self, *, job_id: str, limit: int) -> list[JobMutationAudit]:
        """List mutation audits for one job."""
        with self._sessions.session() as session:
            stmt = (
                select(job_mutation_audits)
                .where(job_mutation_audits.c.job_id == ulid_str_to_bytes(job_id))
                .order_by(job_mutation_audits.c.id.desc())
                .limit(limit)
            )
            rows = session.execute(stmt).mappings().all()
            return [_to_job_mutation_audit(r) for r in rows]

    def create_execution_audit(
        self,
        *,
        execution_id: str,
        job_id: str,
        status: str,
        attempt_number: int,
        retry_after: datetime | None,
        error_message: str | None,
        error_code: str | None,
        created_at: datetime,
    ) -> ExecutionAudit:
        """Persist one execution audit entry."""
        row_id = generate_ulid_bytes()
        with self._sessions.session() as session:
            session.execute(
                execution_audits.insert().values(
                    id=row_id,
                    execution_id=ulid_str_to_bytes(execution_id),
                    job_id=ulid_str_to_bytes(job_id),
                    status=status,
                    attempt_number=attempt_number,
                    retry_after=retry_after,
                    error_message=error_message,
                    error_code=error_code,
                    created_at=created_at,
                )
            )
            row = (
                session.execute(
                    select(execution_audits).where(execution_audits.c.id == row_id)
                )
                .mappings()
                .one()
            )
            return _to_execution_audit(row)

    # ------------------------------------------------------------------
    # Predicate evaluations
    # ------------------------------------------------------------------

    def create_predicate_evaluation(
        self,
        *,
        job_id: str,
        status: str,
        predicate_subject: str,
        predicate_operator: str,
        predicate_value: str | None,
        resolved_value: str | None,
        authorization_decision: str,
        error_code: str | None,
        error_message: str | None,
        trace_id: str,
        created_at: datetime,
    ) -> PredicateEvaluationRecord:
        """Persist one predicate evaluation audit entry."""
        row_id = generate_ulid_bytes()
        with self._sessions.session() as session:
            session.execute(
                predicate_evaluations.insert().values(
                    id=row_id,
                    job_id=ulid_str_to_bytes(job_id),
                    status=status,
                    predicate_subject=predicate_subject,
                    predicate_operator=predicate_operator,
                    predicate_value=predicate_value,
                    resolved_value=resolved_value,
                    authorization_decision=authorization_decision,
                    error_code=error_code,
                    error_message=error_message,
                    trace_id=trace_id,
                    created_at=created_at,
                )
            )
            row = (
                session.execute(
                    select(predicate_evaluations).where(
                        predicate_evaluations.c.id == row_id
                    )
                )
                .mappings()
                .one()
            )
            return _to_predicate_evaluation(row)

    def list_predicate_evaluations(
        self, *, job_id: str, limit: int
    ) -> list[PredicateEvaluationRecord]:
        """List predicate evaluations for one job."""
        with self._sessions.session() as session:
            stmt = (
                select(predicate_evaluations)
                .where(predicate_evaluations.c.job_id == ulid_str_to_bytes(job_id))
                .order_by(predicate_evaluations.c.id.desc())
                .limit(limit)
            )
            rows = session.execute(stmt).mappings().all()
            return [_to_predicate_evaluation(r) for r in rows]

    # ------------------------------------------------------------------
    # Review
    # ------------------------------------------------------------------

    def get_orphaned_jobs(
        self, *, grace_period_hours: int, now: datetime
    ) -> list[JobRecord]:
        """List active jobs with next_run_at past due beyond grace period."""
        threshold = now - timedelta(hours=grace_period_hours)
        with self._sessions.session() as session:
            stmt = select(jobs).where(
                jobs.c.state == JobState.active.value,
                jobs.c.next_run_at.isnot(None),
                jobs.c.next_run_at < threshold,
            )
            rows = session.execute(stmt).mappings().all()
            return [_to_job_record(r) for r in rows]

    def get_failing_jobs(self, *, threshold: int, now: datetime) -> list[JobRecord]:
        """List active jobs with failure_count >= threshold."""
        with self._sessions.session() as session:
            stmt = select(jobs).where(
                jobs.c.state == JobState.active.value,
                jobs.c.failure_count >= threshold,
            )
            rows = session.execute(stmt).mappings().all()
            return [_to_job_record(r) for r in rows]

    def get_ignored_paused_jobs(
        self, *, age_days: int, now: datetime
    ) -> list[JobRecord]:
        """List paused jobs not updated within age_days."""
        threshold = now - timedelta(days=age_days)
        with self._sessions.session() as session:
            stmt = select(jobs).where(
                jobs.c.state == JobState.paused.value,
                jobs.c.updated_at < threshold,
            )
            rows = session.execute(stmt).mappings().all()
            return [_to_job_record(r) for r in rows]

    def create_review_output(
        self,
        *,
        orphaned_count: int,
        failing_count: int,
        ignored_count: int,
        run_at: datetime,
        created_at: datetime,
    ) -> str:
        """Persist one review output and return its id."""
        row_id = generate_ulid_bytes()
        with self._sessions.session() as session:
            session.execute(
                review_outputs.insert().values(
                    id=row_id,
                    orphaned_count=orphaned_count,
                    failing_count=failing_count,
                    ignored_count=ignored_count,
                    run_at=run_at,
                    created_at=created_at,
                )
            )
            return ulid_bytes_to_str(row_id)

    def create_review_item(
        self,
        *,
        review_output_id: str,
        job_id: str,
        category: str,
        severity: str,
        message: str,
        created_at: datetime,
    ) -> None:
        """Persist one review item."""
        with self._sessions.session() as session:
            session.execute(
                review_items.insert().values(
                    id=generate_ulid_bytes(),
                    review_output_id=ulid_str_to_bytes(review_output_id),
                    job_id=ulid_str_to_bytes(job_id),
                    category=category,
                    severity=severity,
                    message=message,
                    created_at=created_at,
                )
            )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def is_healthy(self) -> bool:
        """Return True when backing store is reachable."""
        try:
            with self._sessions.session() as session:
                session.execute(select(1))
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Provider support
    # ------------------------------------------------------------------

    def get_next_due_job(self, *, now: datetime) -> JobRecord | None:
        """Return the active job with the earliest next_run_at <= now."""
        with self._sessions.session() as session:
            stmt = (
                select(jobs)
                .where(
                    jobs.c.state == JobState.active.value,
                    jobs.c.next_run_at.isnot(None),
                    jobs.c.next_run_at <= now,
                )
                .order_by(jobs.c.next_run_at)
                .limit(1)
            )
            row = session.execute(stmt).mappings().one_or_none()
            return None if row is None else _to_job_record(row)

    def get_next_run_time(self) -> datetime | None:
        """Return the earliest next_run_at across all active jobs."""
        with self._sessions.session() as session:
            from sqlalchemy import func

            stmt = select(func.min(jobs.c.next_run_at)).where(
                jobs.c.state == JobState.active.value,
                jobs.c.next_run_at.isnot(None),
            )
            result = session.execute(stmt).scalar()
            return result


# ---------------------------------------------------------------------------
# Row mappers
# ---------------------------------------------------------------------------


def _to_job_intent(row: dict[str, Any]) -> JobIntent:
    """Map one SQL row to JobIntent domain model."""
    action = job_action_adapter.validate_python(
        {
            "type": str(row["action_kind"]),
            "capability_id": str(row["capability_id"]),
            "input_payload": dict(row["input_payload"]),
        }
    )
    return JobIntent(
        id=ulid_bytes_to_str(row["id"]),
        summary=str(row["summary"]),
        action=action,
        details=_opt_str(row, "details"),
        origin_reference=_opt_str(row, "origin_reference"),
        created_by_actor=str(row["created_by_actor"]),
        created_at=_row_dt(row, "created_at"),
        superseded_by_id=(
            ulid_bytes_to_str(row["superseded_by_id"])
            if row.get("superseded_by_id") is not None
            else None
        ),
    )


def _to_job_record(row: dict[str, Any]) -> JobRecord:
    """Map one SQL row to JobRecord domain model."""
    definition = schedule_definition_adapter.validate_python(
        {**row["definition"], "type": str(row["schedule_type"])}
        if "type" not in row["definition"]
        else row["definition"]
    )
    last_run_status_raw = row.get("last_run_status")
    return JobRecord(
        id=ulid_bytes_to_str(row["id"]),
        job_intent_id=ulid_bytes_to_str(row["job_intent_id"]),
        schedule_type=str(row["schedule_type"]),
        state=str(row["state"]),
        timezone=str(row["timezone"]),
        definition=definition,
        next_run_at=_opt_dt(row, "next_run_at"),
        last_run_at=_opt_dt(row, "last_run_at"),
        last_run_status=(
            ExecutionStatus(last_run_status_raw)
            if last_run_status_raw is not None
            else None
        ),
        failure_count=int(row["failure_count"]),
        last_error_message=_opt_str(row, "last_error_message"),
        retry_max_attempts=int(row["retry_max_attempts"]),
        retry_backoff_strategy=BackoffStrategy(row["retry_backoff_strategy"]),
        retry_backoff_base_seconds=int(row["retry_backoff_base_seconds"]),
        origin_trace_id=str(row["origin_trace_id"]),
        origin_envelope_id=str(row["origin_envelope_id"]),
        created_at=_row_dt(row, "created_at"),
        updated_at=_row_dt(row, "updated_at"),
    )


def _to_execution_record(row: dict[str, Any]) -> ExecutionRecord:
    """Map one SQL row to ExecutionRecord domain model."""
    backoff_raw = row.get("retry_backoff_strategy")
    return ExecutionRecord(
        id=ulid_bytes_to_str(row["id"]),
        job_id=ulid_bytes_to_str(row["job_id"]),
        job_intent_id=ulid_bytes_to_str(row["job_intent_id"]),
        scheduled_for=_row_dt(row, "scheduled_for"),
        status=str(row["status"]),
        attempt_number=int(row["attempt_number"]),
        max_attempts=int(row["max_attempts"]),
        retry_backoff_strategy=(
            BackoffStrategy(backoff_raw) if backoff_raw is not None else None
        ),
        retry_after=_opt_dt(row, "retry_after"),
        trace_id=str(row["trace_id"]),
        parent_envelope_id=str(row["parent_envelope_id"]),
        trigger_source=str(row["trigger_source"]),
        started_at=_opt_dt(row, "started_at"),
        finished_at=_opt_dt(row, "finished_at"),
        error_message=_opt_str(row, "error_message"),
        error_code=_opt_str(row, "error_code"),
        created_at=_row_dt(row, "created_at"),
    )


def _to_job_mutation_audit(row: dict[str, Any]) -> JobMutationAudit:
    """Map one SQL row to JobMutationAudit domain model."""
    return JobMutationAudit(
        id=ulid_bytes_to_str(row["id"]),
        job_id=ulid_bytes_to_str(row["job_id"]),
        event_type=str(row["event_type"]),
        actor_type=str(row["actor_type"]),
        actor_id=_opt_str(row, "actor_id"),
        channel=str(row["channel"]),
        trace_id=str(row["trace_id"]),
        diff_summary=_opt_str(row, "diff_summary"),
        notes=_opt_str(row, "notes"),
        created_at=_row_dt(row, "created_at"),
    )


def _to_execution_audit(row: dict[str, Any]) -> ExecutionAudit:
    """Map one SQL row to ExecutionAudit domain model."""
    return ExecutionAudit(
        id=ulid_bytes_to_str(row["id"]),
        execution_id=ulid_bytes_to_str(row["execution_id"]),
        job_id=ulid_bytes_to_str(row["job_id"]),
        status=str(row["status"]),
        attempt_number=int(row["attempt_number"]),
        retry_after=_opt_dt(row, "retry_after"),
        error_message=_opt_str(row, "error_message"),
        error_code=_opt_str(row, "error_code"),
        created_at=_row_dt(row, "created_at"),
    )


def _to_predicate_evaluation(row: dict[str, Any]) -> PredicateEvaluationRecord:
    """Map one SQL row to PredicateEvaluationRecord domain model."""
    return PredicateEvaluationRecord(
        id=ulid_bytes_to_str(row["id"]),
        job_id=ulid_bytes_to_str(row["job_id"]),
        status=PredicateEvaluationStatus(str(row["status"])),
        predicate_subject=str(row["predicate_subject"]),
        predicate_operator=str(row["predicate_operator"]),
        predicate_value=_opt_str(row, "predicate_value"),
        resolved_value=_opt_str(row, "resolved_value"),
        authorization_decision=str(row["authorization_decision"]),
        error_code=_opt_str(row, "error_code"),
        error_message=_opt_str(row, "error_message"),
        trace_id=str(row["trace_id"]),
        created_at=_row_dt(row, "created_at"),
    )


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------


def _row_dt(row: dict[str, Any], column: str) -> datetime:
    """Read and normalize one timezone-aware datetime field from SQL row."""
    value = row.get(column)
    if not isinstance(value, datetime):
        msg = f"expected datetime column for {column}"
        raise ValueError(msg)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _opt_dt(row: dict[str, Any], column: str) -> datetime | None:
    """Read an optional datetime field from SQL row."""
    value = row.get(column)
    if value is None:
        return None
    if not isinstance(value, datetime):
        msg = f"expected datetime column for {column}"
        raise ValueError(msg)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _opt_str(row: dict[str, Any], column: str) -> str | None:
    """Read an optional string field from SQL row."""
    value = row.get(column)
    return str(value) if value is not None else None
