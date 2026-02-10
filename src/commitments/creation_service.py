"""Commitment creation orchestration with validation, dedupe, authority, and scheduling."""

from __future__ import annotations

import logging
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Literal
from uuid import UUID

from sqlalchemy.orm import Session

from commitments.creation_authority import (
    CommitmentCreationSource,
    CreationApprovalProposal,
    evaluate_creation_authority,
)
from commitments.creation_types import CommitmentCreationInput, validate_commitment_creation
from commitments.dedupe import DedupeProposal, generate_dedupe_proposal, list_open_commitments
from commitments.miss_detection_scheduling import MissDetectionScheduleService
from commitments.repository import (
    CommitmentCreateInput,
    CommitmentRepository,
    create_commitment_record,
)
from ingestion.provenance import ProvenanceSourceInput, record_provenance
from llm import LLMClient
from models import Commitment
from scheduler.adapter_interface import SchedulerAdapter
from scheduler.schedule_service import ScheduleCommandServiceImpl
from scheduler.schedule_service_interface import ActorContext, ScheduleDeleteRequest

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommitmentProvenanceLinkInput:
    """Input metadata used to link a commitment to ingestion provenance records."""

    object_key: str
    ingestion_id: UUID
    sources: Iterable[ProvenanceSourceInput]


@dataclass(frozen=True)
class CommitmentSourceContext:
    """Inbound source taxonomy captured at commitment intake time."""

    source_actor: str | None
    source_medium: str | None
    source_uri: str | None
    intake_channel: Literal["signal", "ingest"] | None


@dataclass(frozen=True)
class CommitmentCreationRequest:
    """Creation request combining validated input payloads with source metadata."""

    payload: CommitmentCreationInput | dict
    authority: CommitmentCreationSource | str | None = None
    source_context: CommitmentSourceContext | None = None
    source: CommitmentCreationSource | str | None = None
    confidence: float | None = None
    provenance: CommitmentProvenanceLinkInput | None = None
    bypass_dedupe_once: bool = False


@dataclass(frozen=True)
class CommitmentCreationSuccess:
    """Creation result for a successfully persisted commitment."""

    status: Literal["success"]
    commitment: Commitment
    schedule_id: int | None
    provenance_id: UUID | None


@dataclass(frozen=True)
class CommitmentCreationApprovalRequired:
    """Creation result returned when operator approval is required."""

    status: Literal["approval_required"]
    proposal: CreationApprovalProposal


@dataclass(frozen=True)
class CommitmentCreationDedupeRequired:
    """Creation result returned when a dedupe proposal must be reviewed."""

    status: Literal["dedupe_required"]
    proposal: DedupeProposal


CommitmentCreationResult = (
    CommitmentCreationSuccess
    | CommitmentCreationApprovalRequired
    | CommitmentCreationDedupeRequired
)


class CommitmentCreationService:
    """Service that orchestrates commitment creation end-to-end."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        schedule_adapter: SchedulerAdapter,
        *,
        llm_client: LLMClient | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the creation service with persistence and scheduling dependencies."""
        self._session_factory = session_factory
        self._schedule_adapter = schedule_adapter
        self._llm_client = llm_client
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._schedule_service = MissDetectionScheduleService(
            session_factory,
            schedule_adapter,
            now_provider=self._now_provider,
        )
        self._commitment_repo = CommitmentRepository(session_factory)

    def create(
        self,
        request: CommitmentCreationRequest,
    ) -> CommitmentCreationResult:
        """Create a commitment or return a proposal if dedupe/approval is required."""
        validated = self._validate_request(request)
        if not request.bypass_dedupe_once:
            dedupe = self._check_dedupe(validated)
            if dedupe is not None:
                return CommitmentCreationDedupeRequired(status="dedupe_required", proposal=dedupe)

        authority_source = _resolve_authority_source(request)
        authority = evaluate_creation_authority(
            authority_source,
            confidence=request.confidence,
        )
        if not authority.allow_create:
            if authority.proposal is None:
                raise ValueError("Authority decision requires a proposal when creation is blocked.")
            return CommitmentCreationApprovalRequired(
                status="approval_required",
                proposal=authority.proposal,
            )

        commitment, provenance_id = self._persist_commitment(validated, request.provenance)
        schedule_id = None
        if commitment.due_by is not None:
            try:
                schedule_id = self._schedule_service.ensure_schedule(
                    commitment_id=commitment.commitment_id,
                    due_by=commitment.due_by,
                ).schedule_id
            except Exception as exc:  # noqa: BLE001 - surface root error after rollback
                from scheduler.schedule_service_interface import ScheduleValidationError

                # Allow commitment creation even if scheduling fails for past due dates
                # The commitment is still valid, just can't schedule future miss detection
                if isinstance(exc, ScheduleValidationError) and "must be in the future" in str(exc):
                    LOGGER.warning(
                        "Skipping miss detection schedule for commitment %s: due_by is in the past",
                        commitment.commitment_id,
                    )
                    schedule_id = None
                else:
                    # For other scheduling errors, rollback and fail
                    self._rollback_creation(
                        commitment_id=commitment.commitment_id,
                        error=exc,
                    )
                    raise

        return CommitmentCreationSuccess(
            status="success",
            commitment=commitment,
            schedule_id=schedule_id,
            provenance_id=provenance_id,
        )

    def _validate_request(
        self,
        request: CommitmentCreationRequest,
    ) -> CommitmentCreationInput:
        """Validate and normalize the incoming creation payload."""
        return validate_commitment_creation(request.payload)

    def _check_dedupe(
        self,
        validated: CommitmentCreationInput,
    ) -> DedupeProposal | None:
        """Run dedupe comparison against existing commitments."""
        candidates = list_open_commitments(self._session_factory)
        return generate_dedupe_proposal(
            description=validated.description,
            candidates=candidates,
            client=self._llm_client,
        )

    def _persist_commitment(
        self,
        validated: CommitmentCreationInput,
        provenance: CommitmentProvenanceLinkInput | None,
    ) -> tuple[Commitment, UUID | None]:
        """Persist the commitment and linked provenance in a single transaction."""
        with closing(self._session_factory()) as session:
            session.expire_on_commit = False
            try:
                timestamp = self._now_provider()
                provenance_id = self._resolve_provenance_id(
                    session,
                    validated,
                    provenance,
                    now=timestamp,
                )
                commitment = create_commitment_record(
                    session,
                    CommitmentCreateInput(
                        description=validated.description,
                        provenance_id=provenance_id,
                        state=validated.state,
                        importance=validated.importance,
                        effort_provided=validated.effort_provided,
                        effort_inferred=validated.effort_inferred,
                        due_by=validated.due_by,
                    ),
                    now=timestamp,
                )
                session.commit()
            except Exception:
                session.rollback()
                raise
        return commitment, provenance_id

    def _resolve_provenance_id(
        self,
        session: Session,
        validated: CommitmentCreationInput,
        provenance: CommitmentProvenanceLinkInput | None,
        *,
        now: datetime,
    ) -> UUID | None:
        """Return the provenance_id to store on the commitment."""
        if validated.provenance_id is not None:
            return validated.provenance_id
        if provenance is None:
            return None
        record = record_provenance(
            session,
            object_key=provenance.object_key,
            ingestion_id=provenance.ingestion_id,
            sources=provenance.sources,
            now=now,
        )
        return record.id

    def _rollback_creation(
        self,
        *,
        commitment_id: int,
        error: Exception,
    ) -> None:
        """Best-effort rollback when schedule creation fails."""
        schedule_id = _extract_schedule_id(error)
        if schedule_id is not None:
            try:
                _cancel_schedule(
                    self._session_factory,
                    self._schedule_adapter,
                    schedule_id,
                )
            except Exception:
                pass
        self._commitment_repo.delete(commitment_id)


def _extract_schedule_id(error: Exception) -> int | None:
    """Extract a schedule identifier from a schedule service error payload."""
    details = getattr(error, "details", None)
    if not isinstance(details, dict):
        return None
    schedule_id = details.get("schedule_id")
    if isinstance(schedule_id, int):
        return schedule_id
    if isinstance(schedule_id, str) and schedule_id.isdigit():
        return int(schedule_id)
    return None


def _resolve_authority_source(request: CommitmentCreationRequest) -> CommitmentCreationSource | str:
    """Resolve authority source from explicit authority input or legacy source."""
    if request.authority is not None:
        return request.authority
    if request.source is not None:
        return request.source
    raise ValueError("Commitment creation authority is required.")


def _cancel_schedule(
    session_factory: Callable[[], Session],
    schedule_adapter: SchedulerAdapter,
    schedule_id: int,
) -> None:
    """Cancel a schedule using the scheduler service interface."""
    actor = ActorContext(
        actor_type="system",
        actor_id=None,
        channel="system",
        trace_id=f"commitments.creation.rollback:{schedule_id}",
        reason="commitment_creation_rollback",
    )
    service = ScheduleCommandServiceImpl(
        session_factory,
        schedule_adapter,
    )
    service.delete_schedule(
        ScheduleDeleteRequest(
            schedule_id=schedule_id,
            reason="commitment_creation_rollback",
        ),
        actor,
    )


__all__ = [
    "CommitmentCreationApprovalRequired",
    "CommitmentCreationDedupeRequired",
    "CommitmentCreationRequest",
    "CommitmentSourceContext",
    "CommitmentCreationResult",
    "CommitmentCreationService",
    "CommitmentCreationSuccess",
    "CommitmentProvenanceLinkInput",
]
