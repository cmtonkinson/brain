"""Retry policy helpers for stage-level ingestion retries."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from typing import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from models import IngestionStageRun
from services.database import get_sync_session


@dataclass(frozen=True)
class StageRetryDecision:
    """Decision on whether a stage should run or be skipped due to prior success."""

    should_run: bool
    reason: str | None


class RetryPolicy:
    """Helper for determining whether a stage should run based on prior outcomes."""

    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        """Initialize the retry policy with a database session factory."""
        self._session_factory = session_factory or get_sync_session

    def should_run_stage(self, ingestion_id: str, stage: str) -> StageRetryDecision:
        """
        Determine whether a stage should run based on prior outcomes.

        A stage should run if:
        - No prior stage run exists (first attempt)
        - The most recent stage run failed or was skipped

        A stage should NOT run if:
        - The most recent stage run succeeded

        Args:
            ingestion_id: The ingestion identifier (string or UUID).
            stage: Stage name ('store', 'extract', 'normalize', 'anchor').

        Returns:
            StageRetryDecision indicating whether the stage should run and why.
        """
        # Convert string to UUID if needed
        ingestion_uuid = UUID(ingestion_id) if isinstance(ingestion_id, str) else ingestion_id

        with closing(self._session_factory()) as session:
            most_recent = (
                session.query(IngestionStageRun)
                .filter(
                    IngestionStageRun.ingestion_id == ingestion_uuid,
                    IngestionStageRun.stage == stage,
                )
                .order_by(IngestionStageRun.created_at.desc())
                .first()
            )

        if most_recent is None:
            return StageRetryDecision(
                should_run=True,
                reason="no prior stage run exists",
            )

        if most_recent.status == "success":
            return StageRetryDecision(
                should_run=False,
                reason=f"stage already succeeded at {most_recent.finished_at}",
            )

        if most_recent.status == "failed":
            return StageRetryDecision(
                should_run=True,
                reason=f"retrying failed stage (previous error: {most_recent.error})",
            )

        if most_recent.status == "skipped":
            return StageRetryDecision(
                should_run=True,
                reason=f"retrying skipped stage (previous reason: {most_recent.error})",
            )

        # Fallback for unexpected status values
        return StageRetryDecision(
            should_run=True,
            reason=f"unknown status: {most_recent.status}",
        )


def check_should_retry_stage(
    ingestion_id: str,
    stage: str,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> StageRetryDecision:
    """
    Check whether a stage should run based on prior outcomes.

    This is a convenience function that creates a RetryPolicy and checks the decision.

    Args:
        ingestion_id: The ingestion identifier.
        stage: Stage name ('store', 'extract', 'normalize', 'anchor').
        session_factory: Optional database session factory.

    Returns:
        StageRetryDecision indicating whether the stage should run and why.
    """
    policy = RetryPolicy(session_factory=session_factory)
    return policy.should_run_stage(ingestion_id, stage)
