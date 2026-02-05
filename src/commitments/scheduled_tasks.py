"""Commitment scheduled task handlers for scheduler callbacks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal

from sqlalchemy.orm import Session

from attention.router import AttentionRouter
from commitments.batch_aggregation import list_batch_due_commitments
from commitments.batch_delivery import deliver_batch_reminder
from commitments.batch_formatting import format_batch_reminder_message
from commitments.miss_detection import handle_miss_detection_callback
from commitments.review_aggregation import aggregate_review_commitments, record_review_run
from commitments.review_delivery import (
    deliver_review_summary,
    mark_review_delivered,
    record_review_items,
)
from commitments.review_dedupe import scan_review_duplicates
from commitments.review_summary import (
    collect_commitment_ids_from_structured,
    generate_review_summary,
)
from llm import LLMClient
from time_utils import to_utc

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommitmentScheduledTaskResult:
    """Outcome of handling a commitment scheduled task."""

    status: Literal["success", "noop", "failed"]
    message: str | None
    attention_required: bool
    error_code: str | None = None


class CommitmentScheduledTaskHandler:
    """Dispatch commitment scheduled tasks based on origin references."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        router: AttentionRouter,
        *,
        owner: str | None = None,
        now_provider: Callable[[], datetime] | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        """Initialize the handler with persistence, routing, and optional overrides."""
        self._session_factory = session_factory
        self._router = router
        self._owner = owner
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._llm_client = llm_client

    def handle(
        self,
        *,
        origin_reference: str | None,
        schedule_id: int,
        trace_id: str | None,
        scheduled_for: datetime | None,
    ) -> CommitmentScheduledTaskResult | None:
        """Handle a commitment scheduled task or return None when not applicable."""
        if origin_reference is None or not origin_reference.startswith("commitments."):
            return None
        if origin_reference.startswith("commitments.miss_detection:"):
            return self._handle_miss_detection(
                schedule_id=schedule_id,
                trace_id=trace_id,
                scheduled_for=scheduled_for,
            )
        if origin_reference == "commitments.daily_batch":
            return self._handle_daily_batch(scheduled_for=scheduled_for)
        if origin_reference == "commitments.weekly_review":
            return self._handle_weekly_review(scheduled_for=scheduled_for)
        logger.error("Unhandled commitment origin_reference=%s", origin_reference)
        return CommitmentScheduledTaskResult(
            status="failed",
            message=f"Unhandled commitment origin_reference: {origin_reference}",
            attention_required=True,
            error_code="unknown_commitment_origin",
        )

    def _handle_miss_detection(
        self,
        *,
        schedule_id: int,
        trace_id: str | None,
        scheduled_for: datetime | None,
    ) -> CommitmentScheduledTaskResult:
        """Handle commitment miss detection callbacks."""
        timestamp = self._resolve_timestamp(scheduled_for)
        result = handle_miss_detection_callback(
            self._session_factory,
            schedule_id=schedule_id,
            trace_id=trace_id,
            now=timestamp,
            router=self._router,
        )
        if result.status == "no_link":
            return CommitmentScheduledTaskResult(
                status="noop",
                message=f"Miss detection ignored: no link for schedule {schedule_id}.",
                attention_required=False,
            )
        if result.status == "noop":
            state = result.commitment_state or "unknown"
            return CommitmentScheduledTaskResult(
                status="noop",
                message=f"Miss detection skipped: commitment already {state}.",
                attention_required=False,
            )
        return CommitmentScheduledTaskResult(
            status="success",
            message=f"Commitment {result.commitment_id} marked MISSED.",
            attention_required=False,
        )

    def _handle_daily_batch(
        self,
        *,
        scheduled_for: datetime | None,
    ) -> CommitmentScheduledTaskResult:
        """Generate and deliver the daily batch reminder."""
        timestamp = self._resolve_timestamp(scheduled_for)
        commitments = list_batch_due_commitments(self._session_factory, now=timestamp)
        message = format_batch_reminder_message(commitments)
        routing_result = deliver_batch_reminder(
            self._router,
            commitments=commitments,
            message=message,
            owner=self._owner,
            now=timestamp,
        )
        if routing_result is None:
            return CommitmentScheduledTaskResult(
                status="noop",
                message="No commitments due for daily batch reminder.",
                attention_required=False,
            )
        return CommitmentScheduledTaskResult(
            status="success",
            message=f"Daily batch reminder delivered ({routing_result.decision}).",
            attention_required=False,
        )

    def _handle_weekly_review(
        self,
        *,
        scheduled_for: datetime | None,
    ) -> CommitmentScheduledTaskResult:
        """Generate and deliver the weekly commitment review."""
        timestamp = self._resolve_timestamp(scheduled_for)
        review_sets = aggregate_review_commitments(self._session_factory)
        duplicates = scan_review_duplicates(self._session_factory, client=self._llm_client)
        summary = generate_review_summary(
            self._session_factory,
            review_sets=review_sets,
            duplicates=duplicates,
            generated_at=timestamp,
        )
        review_run = record_review_run(
            self._session_factory,
            run_at=timestamp,
            owner=self._owner,
        )
        commitment_ids = collect_commitment_ids_from_structured(summary.structured)
        record_review_items(
            review_run.id,
            commitment_ids,
            session_factory=self._session_factory,
            created_at=timestamp,
        )
        routing_result = deliver_review_summary(
            self._router,
            review_id=review_run.id,
            summary=summary,
            owner=self._owner,
            now=timestamp,
        )
        if routing_result.decision == "DELIVER":
            mark_review_delivered(
                review_run.id,
                session_factory=self._session_factory,
                delivered_at=timestamp,
            )
        return CommitmentScheduledTaskResult(
            status="success",
            message=f"Weekly review delivered ({routing_result.decision}).",
            attention_required=False,
        )

    def _resolve_timestamp(self, scheduled_for: datetime | None) -> datetime:
        """Resolve the timestamp used for scheduled task execution."""
        return to_utc(scheduled_for or self._now_provider())


__all__ = [
    "CommitmentScheduledTaskHandler",
    "CommitmentScheduledTaskResult",
]
