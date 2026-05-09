"""Commitment Service abstract base class defining the public API."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import date, datetime

from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from services.effect.relay.service import RelayService
from services.effect.language.service import LanguageService
from services.reason.commitment.domain import (
    CommitmentHistoryResult,
    CommitmentListResult,
    CommitmentMutationResult,
    CommitmentRecord,
    CommitmentReviewItem,
    CommitmentReviewRun,
    ExtractCandidatesResult,
    HealthStatus,
    LoopClosureResolutionResult,
    MissDetectionResult,
    ReviewDeliveryResult,
)
from services.reason.job.service import JobService


class CommitmentService(ABC):
    """Public API for commitment lifecycle, review, and loop closure."""

    @abstractmethod
    def create_commitment(
        self,
        *,
        meta: EnvelopeMeta,
        description: str,
        provenance_reference: str | None = None,
        ingestion_id: str | None = None,
        source: str | None = None,
        due_by: datetime | date | None = None,
        due_timezone: str | None = None,
        importance: int = 2,
        effort_provided: int = 2,
        effort_inferred: int | None = None,
        confidence: float | None = None,
        requested_by: str = "operator",
    ) -> Envelope[CommitmentMutationResult]:
        """Create one commitment or persist a creation proposal."""

    @abstractmethod
    def ingest_commitment_candidate(
        self,
        *,
        meta: EnvelopeMeta,
        description: str,
        provenance_reference: str | None = None,
        ingestion_id: str | None = None,
        source: str | None = None,
        due_by: datetime | date | None = None,
        due_timezone: str | None = None,
        importance: int = 2,
        effort_provided: int = 2,
        effort_inferred: int | None = None,
        confidence: float | None = None,
        requested_by: str = "service",
    ) -> Envelope[CommitmentMutationResult]:
        """Accept one typed ingestion-derived commitment candidate."""

    @abstractmethod
    def update_commitment(
        self,
        *,
        meta: EnvelopeMeta,
        commitment_id: str,
        description: str | None = None,
        provenance_reference: str | None = None,
        ingestion_id: str | None = None,
        source: str | None = None,
        due_by: datetime | date | None = None,
        due_timezone: str | None = None,
        importance: int | None = None,
        effort_provided: int | None = None,
        effort_inferred: int | None = None,
        reviewed_at: datetime | None = None,
    ) -> Envelope[CommitmentMutationResult]:
        """Update one commitment without changing lifecycle state."""

    @abstractmethod
    def transition_commitment(
        self,
        *,
        meta: EnvelopeMeta,
        commitment_id: str,
        to_state: str,
        requested_by: str,
        reason: str | None = None,
        confidence: float | None = None,
    ) -> Envelope[CommitmentMutationResult]:
        """Apply one lifecycle transition or persist a transition proposal."""

    @abstractmethod
    def record_progress(
        self,
        *,
        meta: EnvelopeMeta,
        commitment_id: str,
        provenance_reference: str | None = None,
        occurred_at: datetime,
        summary: str,
        snippet: str | None = None,
    ) -> Envelope[CommitmentMutationResult]:
        """Record one progress entry and update last_progress_at atomically."""

    @abstractmethod
    def resolve_loop_closure_reply(
        self, *, meta: EnvelopeMeta, **payload: object
    ) -> Envelope[LoopClosureResolutionResult]:
        """Resolve one normalized loop-closure reply."""

    @abstractmethod
    def apply_creation_proposal_decision(
        self, *, meta: EnvelopeMeta, **payload: object
    ) -> Envelope[CommitmentMutationResult]:
        """Approve or reject one pending creation proposal."""

    @abstractmethod
    def apply_transition_proposal_decision(
        self, *, meta: EnvelopeMeta, **payload: object
    ) -> Envelope[CommitmentMutationResult]:
        """Approve or reject one pending transition proposal."""

    @abstractmethod
    def get_commitment(
        self, *, meta: EnvelopeMeta, commitment_id: str
    ) -> Envelope[CommitmentRecord]:
        """Read one commitment by id."""

    @abstractmethod
    def list_commitments(
        self,
        *,
        meta: EnvelopeMeta,
        state: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Envelope[CommitmentListResult]:
        """List commitments with optional state filter and cursor pagination."""

    @abstractmethod
    def get_commitment_history(
        self, *, meta: EnvelopeMeta, commitment_id: str
    ) -> Envelope[CommitmentHistoryResult]:
        """Return one commitment plus progress and transition history."""

    @abstractmethod
    def get_review_run(
        self, *, meta: EnvelopeMeta, review_run_id: str
    ) -> Envelope[CommitmentReviewRun]:
        """Read one review run by id."""

    @abstractmethod
    def list_review_runs(
        self, *, meta: EnvelopeMeta, limit: int = 50, cursor: str | None = None
    ) -> Envelope[tuple[CommitmentReviewRun, ...]]:
        """List review runs."""

    @abstractmethod
    def list_review_items(
        self, *, meta: EnvelopeMeta, review_run_id: str
    ) -> Envelope[tuple[CommitmentReviewItem, ...]]:
        """List review items for one run."""

    @abstractmethod
    def ensure_follow_up_job(
        self, *, meta: EnvelopeMeta, commitment_id: str
    ) -> Envelope[CommitmentMutationResult]:
        """Ensure one active follow-up job exists for one commitment."""

    @abstractmethod
    def remove_follow_up_job(
        self, *, meta: EnvelopeMeta, commitment_id: str
    ) -> Envelope[CommitmentMutationResult]:
        """Remove any active follow-up job for one commitment."""

    @abstractmethod
    def run_miss_detection(
        self, *, meta: EnvelopeMeta, commitment_id: str | None = None
    ) -> Envelope[MissDetectionResult]:
        """Detect and mark due open commitments as MISSED."""

    @abstractmethod
    def build_review_sets(self, *, meta: EnvelopeMeta) -> Envelope[CommitmentReviewRun]:
        """Build and persist one review run and its items."""

    @abstractmethod
    def deliver_review(
        self, *, meta: EnvelopeMeta, review_run_id: str
    ) -> Envelope[ReviewDeliveryResult]:
        """Deliver one review run through Relay outbound."""

    @abstractmethod
    def extract_commitment_candidates(
        self,
        *,
        meta: EnvelopeMeta,
        text: str,
        context: str = "",
    ) -> Envelope[ExtractCandidatesResult]:
        """Extract zero or more commitment candidate signals from arbitrary text."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Commitment Service readiness state."""


def build_commitment_service(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> CommitmentService:
    """Build concrete Commitment Service from typed settings and peer services."""
    from services.reason.commitment.config import resolve_commitment_service_settings
    from services.reason.commitment.data import (
        CommitmentPostgresRuntime,
        PostgresCommitmentRepository,
    )
    from services.reason.commitment.implementation import DefaultCommitmentService

    runtime = CommitmentPostgresRuntime.from_settings(settings)
    repository = PostgresCommitmentRepository(sessions=runtime.schema_sessions)
    job_service = components.get("service_job")
    if not isinstance(job_service, JobService):
        raise KeyError("service_job")
    outbound = components.get("service_relay")
    if outbound is not None and not isinstance(outbound, RelayService):
        raise KeyError("service_relay")
    language_service = components.get("service_language")
    if language_service is not None and not isinstance(
        language_service, LanguageService
    ):
        raise KeyError("service_language")
    return DefaultCommitmentService(
        settings=resolve_commitment_service_settings(settings),
        repository=repository,
        runtime=runtime,
        job_service=job_service,
        outbound_service=outbound,
        language_service=language_service,
    )
