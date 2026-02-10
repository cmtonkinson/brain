"""Ingestion hook for extracting and creating commitments from ingested content."""

from __future__ import annotations

import logging
from hashlib import sha1
from contextlib import closing
from typing import Callable, Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from attention.envelope_schema import ProvenanceInput
from attention.router import AttentionRouter
from commitments.creation_service import (
    CommitmentCreationApprovalRequired,
    CommitmentCreationDedupeRequired,
    CommitmentCreationRequest,
    CommitmentCreationService,
    CommitmentSourceContext,
    CommitmentCreationSuccess,
    CommitmentProvenanceLinkInput,
)
from commitments.creation_authority import CreationApprovalProposal
from commitments.dedupe import DedupeProposal
from commitments.notifications import (
    CommitmentNotification,
    CommitmentNotificationType,
    submit_commitment_notification,
)
from commitments.extraction import extract_commitments_from_text
from commitments.progress_service import CommitmentProgressService
from ingestion.provenance import ProvenanceSourceInput
from llm import LLMClient
from models import Artifact, ProvenanceRecord, ProvenanceSource
from scheduler.adapter_interface import SchedulerAdapter
from services.object_store import ObjectStore

LOGGER = logging.getLogger(__name__)


def create_commitment_extraction_hook(
    session_factory: Callable[[], Session],
    schedule_adapter: SchedulerAdapter,
    object_store: ObjectStore,
    llm_client: LLMClient | None = None,
    router: AttentionRouter | None = None,
) -> Callable[[UUID, str, Sequence[ProvenanceRecord]], None]:
    """Create a hook callback that extracts and creates commitments from ingested content.

    Args:
        session_factory: Factory for creating database sessions
        schedule_adapter: Scheduler adapter for miss detection scheduling
        object_store: Object store for reading artifact content
        llm_client: Optional LLM client for extraction

    Returns:
        A hook callback compatible with the ingestion hook registry
    """
    creation_service = CommitmentCreationService(
        session_factory,
        schedule_adapter,
        llm_client=llm_client,
    )
    progress_service = CommitmentProgressService(session_factory)
    resolved_router = router or AttentionRouter()

    def commitment_extraction_hook(
        ingestion_id: UUID,
        stage: str,
        records: Sequence[ProvenanceRecord],
    ) -> None:
        """Extract commitments from ingested content and create them.

        Args:
            ingestion_id: The ingestion ID for this batch
            stage: The ingestion stage that completed
            records: Provenance records for the completed artifacts
        """
        if not records:
            LOGGER.debug(
                "No provenance records for ingestion=%s stage=%s, skipping commitment extraction",
                ingestion_id,
                stage,
            )
            return

        LOGGER.info(
            "Processing %s provenance record(s) for commitment extraction: ingestion=%s stage=%s",
            len(records),
            ingestion_id,
            stage,
        )

        for record in records:
            try:
                _process_record(
                    record=record,
                    ingestion_id=ingestion_id,
                    creation_service=creation_service,
                    progress_service=progress_service,
                    object_store=object_store,
                    session_factory=session_factory,
                    llm_client=llm_client,
                    router=resolved_router,
                )
            except Exception:
                LOGGER.exception(
                    "Failed to process commitment extraction for record: object_key=%s",
                    record.object_key,
                )

    return commitment_extraction_hook


def _process_record(
    record: ProvenanceRecord,
    ingestion_id: UUID,
    creation_service: CommitmentCreationService,
    progress_service: CommitmentProgressService,
    object_store: ObjectStore,
    session_factory: Callable[[], Session],
    llm_client: LLMClient | None,
    router: AttentionRouter,
) -> None:
    """Process a single provenance record for commitment extraction."""
    # Load artifact metadata and check if it's text content
    with closing(session_factory()) as session:
        artifact = session.query(Artifact).filter(Artifact.object_key == record.object_key).first()
        if artifact is None:
            LOGGER.warning(
                "Artifact not found for provenance record: object_key=%s",
                record.object_key,
            )
            return

        # Only process text content
        if artifact.mime_type not in ("text/plain", "text/markdown", "text/html"):
            LOGGER.debug(
                "Skipping non-text artifact: object_key=%s mime_type=%s",
                record.object_key,
                artifact.mime_type,
            )
            return

        # Load provenance sources for linking
        sources = (
            session.query(ProvenanceSource)
            .filter(
                ProvenanceSource.provenance_id == record.id,
                ProvenanceSource.ingestion_id == ingestion_id,
            )
            .all()
        )

    # Read content from object store
    try:
        content_bytes = object_store.read(record.object_key)
        content_text = content_bytes.decode("utf-8", errors="replace")
    except Exception:
        LOGGER.exception(
            "Failed to read artifact content: object_key=%s",
            record.object_key,
        )
        return

    # Extract commitments using LLM
    try:
        extractions = extract_commitments_from_text(
            content_text,
            client=llm_client,
        )
    except Exception:
        LOGGER.exception(
            "Failed to extract commitments from text: object_key=%s",
            record.object_key,
        )
        return

    if not extractions:
        LOGGER.debug(
            "No commitments extracted from artifact: object_key=%s",
            record.object_key,
        )
        return

    LOGGER.info(
        "Extracted %s commitment(s) from artifact: object_key=%s",
        len(extractions),
        record.object_key,
    )

    # Create commitments
    for extraction_index, extraction in enumerate(extractions, start=1):
        try:
            # Build provenance link
            provenance_sources = [
                ProvenanceSourceInput(
                    source_type=source.source_type,
                    source_uri=source.source_uri,
                    source_actor=source.source_actor,
                    captured_at=source.captured_at,
                )
                for source in sources
            ]

            provenance_link = CommitmentProvenanceLinkInput(
                object_key=record.object_key,
                ingestion_id=ingestion_id,
                sources=provenance_sources,
            )

            # Create commitment request
            source_context = _build_ingest_source_context(sources)
            request = CommitmentCreationRequest(
                payload=extraction,
                authority="agent",
                confidence=extraction.get("confidence"),
                source_context=source_context,
                provenance=provenance_link,
            )

            # Attempt creation
            result = creation_service.create(request)

            # Handle result
            if isinstance(result, CommitmentCreationDedupeRequired):
                LOGGER.info(
                    "Commitment creation requires dedupe review: %s",
                    result.proposal,
                )
                _route_ingestion_dedupe_proposal(
                    router=router,
                    proposal=result.proposal,
                    extraction=extraction,
                    ingestion_id=ingestion_id,
                    object_key=record.object_key,
                    extraction_index=extraction_index,
                )
            elif isinstance(result, CommitmentCreationApprovalRequired):
                LOGGER.info(
                    "Commitment creation requires approval: %s",
                    result.proposal,
                )
                _route_ingestion_approval_proposal(
                    router=router,
                    proposal=result.proposal,
                    extraction=extraction,
                    ingestion_id=ingestion_id,
                    object_key=record.object_key,
                    extraction_index=extraction_index,
                )
            else:
                LOGGER.info(
                    "Commitment created successfully: commitment_id=%s description=%s",
                    result.commitment.commitment_id,
                    result.commitment.description[:100],
                )
                # Record progress for successful creation
                if isinstance(result, CommitmentCreationSuccess):
                    try:
                        # Use content snippet for progress record
                        snippet = content_text[:200] if len(content_text) <= 500 else None
                        progress_service.record_progress(
                            commitment_id=result.commitment.commitment_id,
                            provenance_id=result.provenance_id,
                            occurred_at=record.updated_at,
                            summary="Commitment created from ingested artifact",
                            snippet=snippet,
                            metadata={
                                "object_key": record.object_key,
                                "ingestion_id": str(ingestion_id),
                                "intake_channel": "ingest",
                            },
                        )
                        LOGGER.debug(
                            "Recorded progress for commitment_id=%s",
                            result.commitment.commitment_id,
                        )
                    except Exception:
                        LOGGER.exception(
                            "Failed to record progress for commitment_id=%s",
                            result.commitment.commitment_id,
                        )
        except Exception:
            LOGGER.exception(
                "Failed to create commitment from extraction: %s",
                extraction.get("description", "unknown"),
            )


def _route_ingestion_dedupe_proposal(
    *,
    router: AttentionRouter,
    proposal: DedupeProposal,
    extraction: dict,
    ingestion_id: UUID,
    object_key: str,
    extraction_index: int,
) -> None:
    """Route ingestion dedupe proposals through the commitment notification path."""
    description = str(extraction.get("description", "")).strip()
    proposal_ref = _build_ingestion_proposal_reference(
        proposal_kind="dedupe",
        ingestion_id=ingestion_id,
        object_key=object_key,
        extraction_index=extraction_index,
        description=description,
    )
    message = (
        "Dedupe review needed for extracted commitment: "
        f'"{description or "Unspecified commitment"}". '
        f"Potential duplicate commitment_id={proposal.candidate.commitment_id} "
        f"(confidence={proposal.confidence:.2f}, threshold={proposal.threshold:.2f}). "
        f"proposal_ref={proposal_ref}"
    )
    notification = CommitmentNotification(
        commitment_id=proposal.candidate.commitment_id,
        notification_type=CommitmentNotificationType.DEDUPE_PROPOSAL,
        message=message,
        channel="signal",
        signal_reference=f"commitment.dedupe_proposal:{proposal_ref}",
        provenance=[
            ProvenanceInput(
                input_type="proposal_ref",
                reference=proposal_ref,
                description="Stable dedupe proposal reference.",
            ),
            ProvenanceInput(
                input_type="ingestion",
                reference=str(ingestion_id),
                description="Ingestion run that surfaced the extracted commitment.",
            ),
            ProvenanceInput(
                input_type="artifact",
                reference=object_key,
                description=f"Artifact object_key from extraction index={extraction_index}.",
            ),
        ],
    )
    _submit_ingestion_proposal_notification(router, notification, proposal_ref=proposal_ref)


def _route_ingestion_approval_proposal(
    *,
    router: AttentionRouter,
    proposal: CreationApprovalProposal,
    extraction: dict,
    ingestion_id: UUID,
    object_key: str,
    extraction_index: int,
) -> None:
    """Route ingestion approval proposals through the commitment notification path."""
    description = str(extraction.get("description", "")).strip()
    proposal_ref = _build_ingestion_proposal_reference(
        proposal_kind="approval",
        ingestion_id=ingestion_id,
        object_key=object_key,
        extraction_index=extraction_index,
        description=description,
    )
    message = (
        "Approval needed for extracted commitment creation: "
        f'"{description or "Unspecified commitment"}". '
        f"Source={proposal.source.value} "
        f"(confidence={proposal.confidence:.2f}, threshold={proposal.threshold:.2f}). "
        f"Reason={proposal.reason}. proposal_ref={proposal_ref}"
    )
    notification = CommitmentNotification(
        commitment_id=None,
        notification_type=CommitmentNotificationType.CREATION_APPROVAL_PROPOSAL,
        message=message,
        channel="signal",
        signal_reference=f"commitment.creation_approval_proposal:{proposal_ref}",
        provenance=[
            ProvenanceInput(
                input_type="proposal_ref",
                reference=proposal_ref,
                description="Stable creation approval proposal reference.",
            ),
            ProvenanceInput(
                input_type="ingestion",
                reference=str(ingestion_id),
                description="Ingestion run that surfaced the extracted commitment.",
            ),
            ProvenanceInput(
                input_type="artifact",
                reference=object_key,
                description=f"Artifact object_key from extraction index={extraction_index}.",
            ),
        ],
    )
    _submit_ingestion_proposal_notification(router, notification, proposal_ref=proposal_ref)


def _submit_ingestion_proposal_notification(
    router: AttentionRouter,
    notification: CommitmentNotification,
    *,
    proposal_ref: str,
) -> None:
    """Submit proposal notifications without aborting ingestion record processing."""
    try:
        submit_commitment_notification(router, notification)
    except Exception:
        LOGGER.exception(
            "Failed to route ingestion proposal notification: proposal_ref=%s type=%s",
            proposal_ref,
            notification.notification_type.value,
        )


def _build_ingestion_proposal_reference(
    *,
    proposal_kind: str,
    ingestion_id: UUID,
    object_key: str,
    extraction_index: int,
    description: str,
) -> str:
    """Return a deterministic proposal reference for ingestion-created proposals."""
    fingerprint = sha1(
        f"{proposal_kind}|{ingestion_id}|{object_key}|{extraction_index}|{description}".encode(
            "utf-8"
        )
    ).hexdigest()
    return f"ingest:{proposal_kind}:{fingerprint[:16]}"


def _build_ingest_source_context(sources: Sequence[ProvenanceSource]) -> CommitmentSourceContext:
    """Build intake source context for commitments created from ingestion records."""
    if not sources:
        return CommitmentSourceContext(
            source_actor=None,
            source_medium=None,
            source_uri=None,
            intake_channel="ingest",
        )

    primary_source = sources[0]
    return CommitmentSourceContext(
        source_actor=primary_source.source_actor,
        source_medium=primary_source.source_type,
        source_uri=primary_source.source_uri,
        intake_channel="ingest",
    )


__all__ = ["create_commitment_extraction_hook"]
