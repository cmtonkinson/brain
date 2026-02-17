"""Stage outcome recording helpers for ingestion pipeline observability."""

from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Generator
from uuid import UUID

from opentelemetry import trace
from sqlalchemy.orm import Session

from models import Ingestion, IngestionStageRun
from services.database import get_sync_session

tracer = trace.get_tracer(__name__)


@dataclass(frozen=True)
class StageOutcomeRecord:
    """Immutable representation of a stage outcome record."""

    id: UUID
    ingestion_id: UUID
    stage: str
    status: str
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class StageRecorder:
    """Helper for recording per-stage timing, status, and errors during ingestion."""

    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        """Initialize the recorder with a database session factory."""
        self._session_factory = session_factory or get_sync_session

    @contextmanager
    def record_stage(
        self,
        ingestion_id: UUID,
        stage: str,
        *,
        now: datetime | None = None,
    ) -> Generator[StageOutcomeRecord, None, None]:
        """
        Context manager that records stage start/finish timing and outcome.

        Opens a stage run on entry, and finalizes it on exit with success/failed status.
        Sets ingestions.status to 'running' on Stage 1 start, 'failed' on any failure,
        and 'complete' when Stage 4 completes successfully.

        Args:
            ingestion_id: The ingestion identifier.
            stage: Stage name ('store', 'extract', 'normalize', 'anchor').
            now: Optional timestamp override for testing.

        Yields:
            StageOutcomeRecord instance representing the in-progress stage run.

        Raises:
            Any exception raised within the context. The stage run will be marked
            as 'failed' with the error message before re-raising.
        """
        timestamp = now or datetime.now(timezone.utc)
        started_at = timestamp

        # Start OTEL span for observability
        with tracer.start_as_current_span(
            f"ingestion.stage.{stage}",
            attributes={
                "ingestion.id": str(ingestion_id),
                "ingestion.stage": stage,
            },
        ) as span:
            try:
                # Create initial stage run record as "in progress"
                run_id = self._start_stage_run(ingestion_id, stage, started_at)

                # Update ingestion status to 'running' when Stage 1 starts
                if stage == "store":
                    self._update_ingestion_status(ingestion_id, "running", None)

                record = StageOutcomeRecord(
                    id=run_id,
                    ingestion_id=ingestion_id,
                    stage=stage,
                    status="running",
                    error=None,
                    started_at=started_at,
                    finished_at=None,
                )

                try:
                    yield record
                    # Success path
                    finished_at = now or datetime.now(timezone.utc)
                    self._finish_stage_run(run_id, "success", None, finished_at)

                    # Mark ingestion complete when Stage 4 completes successfully
                    if stage == "anchor":
                        self._update_ingestion_status(ingestion_id, "complete", None)

                    # Update span attributes for success
                    span.set_attribute("ingestion.stage.status", "success")

                except Exception as exc:
                    # Failure path
                    finished_at = now or datetime.now(timezone.utc)
                    error_text = str(exc)
                    self._finish_stage_run(run_id, "failed", error_text, finished_at)
                    self._update_ingestion_status(ingestion_id, "failed", error_text)

                    # Update span attributes for failure
                    span.set_attribute("ingestion.stage.status", "failed")
                    span.set_attribute("ingestion.stage.error", error_text)
                    raise

            except Exception as telemetry_exc:
                # Ensure telemetry failures don't alter stage outcomes
                # This outer try-except catches any unexpected errors in OTEL
                # If OTEL fails, we still want the stage logic to proceed
                try:
                    # Log the telemetry failure but don't propagate it
                    import logging

                    logging.getLogger(__name__).warning(
                        "OTEL instrumentation failed for stage %s: %s", stage, telemetry_exc
                    )
                except Exception:
                    # Even logging failures shouldn't break execution
                    pass
                # Re-raise only if it's from the stage execution, not telemetry
                raise

    def record_skipped_stage(
        self,
        ingestion_id: UUID,
        stage: str,
        reason: str,
        *,
        now: datetime | None = None,
    ) -> StageOutcomeRecord:
        """
        Record a skipped stage outcome with a reason.

        Args:
            ingestion_id: The ingestion identifier.
            stage: Stage name ('store', 'extract', 'normalize', 'anchor').
            reason: Explanation for why the stage was skipped.
            now: Optional timestamp override for testing.

        Returns:
            StageOutcomeRecord representing the skipped stage run.
        """
        timestamp = now or datetime.now(timezone.utc)
        run_id = self._start_stage_run(ingestion_id, stage, timestamp)
        self._finish_stage_run(run_id, "skipped", reason, timestamp)
        return StageOutcomeRecord(
            id=run_id,
            ingestion_id=ingestion_id,
            stage=stage,
            status="skipped",
            error=reason,
            started_at=timestamp,
            finished_at=timestamp,
        )

    def _start_stage_run(self, ingestion_id: UUID, stage: str, started_at: datetime) -> UUID:
        """Create a new stage run record and return its ID."""
        with closing(self._session_factory()) as session:
            # Use a placeholder status until we finish the stage
            run = IngestionStageRun(
                ingestion_id=ingestion_id,
                stage=stage,
                status="success",  # Temporary; will be updated on finish
                error=None,
                started_at=started_at,
                finished_at=None,
                created_at=started_at,
            )
            session.add(run)
            session.flush()
            run_id = run.id
            session.commit()
        return run_id

    def _finish_stage_run(
        self, run_id: UUID, status: str, error: str | None, finished_at: datetime
    ) -> None:
        """Update a stage run with final status, error, and finish timestamp."""
        with closing(self._session_factory()) as session:
            run = session.query(IngestionStageRun).filter(IngestionStageRun.id == run_id).first()
            if run is None:
                raise ValueError(f"Stage run not found: {run_id}")
            run.status = status
            run.error = error
            run.finished_at = finished_at
            session.commit()

    def _update_ingestion_status(
        self, ingestion_id: UUID, status: str, last_error: str | None
    ) -> None:
        """Update ingestion status and last_error fields."""
        with closing(self._session_factory()) as session:
            ingestion = session.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
            if ingestion is None:
                raise ValueError(f"Ingestion not found: {ingestion_id}")
            ingestion.status = status
            if last_error is not None:
                ingestion.last_error = last_error
            session.commit()


def record_stage_failure(
    ingestion_id: UUID,
    stage: str,
    error_text: str,
    *,
    session_factory: Callable[[], Session] | None = None,
    now: datetime | None = None,
) -> StageOutcomeRecord:
    """
    Record a stage failure when per-artifact failures occur.

    This is used when a stage encounters partial failures (e.g., Stage 2/3 with
    multiple artifacts where some succeed and some fail). The stage run is marked
    as 'failed' while preserving successful artifact outcomes.

    Args:
        ingestion_id: The ingestion identifier.
        stage: Stage name ('store', 'extract', 'normalize', 'anchor').
        error_text: Error message describing the failure.
        session_factory: Optional database session factory.
        now: Optional timestamp override for testing.

    Returns:
        StageOutcomeRecord representing the failed stage run.
    """
    recorder = StageRecorder(session_factory=session_factory)
    timestamp = now or datetime.now(timezone.utc)
    run_id = recorder._start_stage_run(ingestion_id, stage, timestamp)
    recorder._finish_stage_run(run_id, "failed", error_text, timestamp)
    recorder._update_ingestion_status(ingestion_id, "failed", error_text)
    return StageOutcomeRecord(
        id=run_id,
        ingestion_id=ingestion_id,
        stage=stage,
        status="failed",
        error=error_text,
        started_at=timestamp,
        finished_at=timestamp,
    )
