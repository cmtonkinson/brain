"""Periodic job for reviewing schedule health."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from models import (
    ReviewIssueTypeEnum,
    ReviewItem,
    ReviewOutput,
    ReviewSeverityEnum,
)
from scheduler.data_access import (
    get_failing_schedules,
    get_ignored_schedules,
    get_orphaned_schedules,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReviewJobConfig:
    """Configuration for the review job."""

    orphan_grace_period: timedelta = timedelta(hours=24)
    consecutive_failure_threshold: int = 3
    stale_failure_age: timedelta = timedelta(days=7)
    ignored_pause_age: timedelta = timedelta(days=30)


class ReviewJob:
    """Job to detect and record schedule health issues."""

    def __init__(self, session: Session, config: ReviewJobConfig | None = None) -> None:
        """Initialize the review job.

        Args:
            session: SQLAlchemy session.
            config: Job configuration (defaults will be used if None).
        """
        self._session = session
        self._config = config or ReviewJobConfig()

    def run(self, now: datetime | None = None) -> ReviewOutput:
        """Execute the review job.

        Args:
            now: Reference timestamp (defaults to current UTC time).

        Returns:
            The created ReviewOutput record.
        """
        now = now or datetime.now(timezone.utc)
        window_start = now  # This is a point-in-time check, so start/end are effectively same or could be execution time.
        # For window_end we'll use the completion time, but for the record we will start with 'now'

        orphans = get_orphaned_schedules(
            self._session,
            grace_period=self._config.orphan_grace_period,
            now=now,
        )
        failing = get_failing_schedules(
            self._session,
            consecutive_failure_threshold=self._config.consecutive_failure_threshold,
            stale_failure_age=self._config.stale_failure_age,
            now=now,
        )
        ignored = get_ignored_schedules(
            self._session,
            ignored_age=self._config.ignored_pause_age,
            now=now,
        )

        review_output = ReviewOutput(
            window_start=window_start,
            window_end=now,  # Initially same, effectively instantaneous check
            orphaned_count=len(orphans),
            failing_count=len(failing),
            ignored_count=len(ignored),
            created_at=now,
        )
        self._session.add(review_output)
        self._session.flush()

        for schedule in orphans:
            self._create_review_item(
                review_output.id,
                schedule,
                ReviewIssueTypeEnum.orphaned,
                ReviewSeverityEnum.high,
                f"Schedule missed execution. Next run: {schedule.next_run_at}",
                now=now,
            )

        for schedule in failing:
            self._create_review_item(
                review_output.id,
                schedule,
                ReviewIssueTypeEnum.failing,
                ReviewSeverityEnum.medium,
                f"Schedule failing. Count: {schedule.failure_count}, Last status: {schedule.last_run_status}",
                last_error_message=None,
                now=now,
            )

        for schedule in ignored:
            self._create_review_item(
                review_output.id,
                schedule,
                ReviewIssueTypeEnum.ignored,
                ReviewSeverityEnum.low,
                f"Schedule paused since {schedule.updated_at}",
                now=now,
            )

        # update window_end to capture processing time if needed, otherwise 'now' is fine.
        # Actually persistence usually happens at end.
        # Let's just keep window_end as 'now' for this instantaneous check.

        self._session.flush()
        return review_output

    def _create_review_item(
        self,
        review_output_id: int,
        schedule: Any,  # Typed as Any to avoid circular import or just imply Schedule model
        issue_type: ReviewIssueTypeEnum,
        severity: ReviewSeverityEnum,
        description: str,
        last_error_message: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Create and add a review item."""

        # Logic to fetch error message if not provided for failures
        if issue_type == ReviewIssueTypeEnum.failing and not last_error_message:
            if schedule.last_execution_id:
                # Need to fetch execution to get error message.
                # We can access `schedule.executions` if relationship is set up, or query.
                # models.py shows last_execution_id FK.
                # Let's check if we can access the relationship directly.
                # SQLAlchemy usually provides it if defined.
                # Looking at models.py... Schedule has last_execution_id but NO relationship property defined back to Execution explicitly for that FK in the snippet provided.
                # However, Execution has FK to Schedule.
                # Might need to query Execution manually or rely on lazy loading if relationship existed (it doesn't seem to be in the snippet).
                # Actually, `last_execution_id` is on Schedule.
                # Let's just query it if we have the session?
                from models import Execution

                execution = (
                    self._session.query(Execution)
                    .filter(Execution.id == schedule.last_execution_id)
                    .first()
                )
                if execution:
                    last_error_message = execution.last_error_message

        item = ReviewItem(
            review_output_id=review_output_id,
            schedule_id=schedule.id,
            task_intent_id=schedule.task_intent_id,
            issue_type=issue_type,
            severity=severity,
            description=description,
            last_error_message=last_error_message,
            created_at=now or datetime.now(timezone.utc),
        )
        self._session.add(item)
