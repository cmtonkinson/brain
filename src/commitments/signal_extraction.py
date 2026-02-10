"""Commitment extraction from Signal message exchanges."""

from __future__ import annotations

import logging
from hashlib import sha1
from datetime import datetime
from typing import Callable

from sqlalchemy.orm import Session

from commitments.creation_service import (
    CommitmentCreationApprovalRequired,
    CommitmentCreationDedupeRequired,
    CommitmentCreationRequest,
    CommitmentCreationService,
    CommitmentSourceContext,
    CommitmentCreationSuccess,
)
from commitments.creation_proposal_notifications import (
    ProposalRoutingContext,
    route_creation_proposal_notification,
)
from commitments.extraction import extract_commitments_from_text
from commitments.progress_service import CommitmentProgressService
from llm import LLMClient
from attention.envelope_schema import ProvenanceInput
from attention.router import AttentionRouter
from scheduler.adapter_interface import SchedulerAdapter

LOGGER = logging.getLogger(__name__)


def extract_and_create_commitments_from_signal(
    user_message: str,
    agent_response: str,
    sender: str,
    timestamp: datetime,
    session_factory: Callable[[], Session],
    creation_service: CommitmentCreationService,
    llm_client: LLMClient | None = None,
    progress_service: CommitmentProgressService | None = None,
    router: AttentionRouter | None = None,
) -> None:
    """Extract and create commitments from a Signal message exchange.

    Analyzes both the user's message and the agent's response for commitments,
    then creates them using the CommitmentCreationService.

    Args:
        user_message: The message sent by the user
        agent_response: The agent's response
        sender: The Signal phone number of the sender
        timestamp: When the message was received
        creation_service: Service for creating commitments
        llm_client: Optional LLM client for extraction
    """
    if not llm_client:
        LOGGER.debug("No LLM client provided, skipping Signal commitment extraction")
        return

    # Combine message and response for context-aware extraction
    combined_text = f"""User: {user_message}

Agent: {agent_response}"""

    LOGGER.info(
        "Extracting commitments from Signal exchange: sender=%s message_len=%s response_len=%s",
        sender,
        len(user_message),
        len(agent_response),
    )

    # Extract commitments using LLM
    try:
        extractions = extract_commitments_from_text(
            combined_text,
            client=llm_client,
        )
    except Exception:
        LOGGER.exception("Failed to extract commitments from Signal exchange")
        return

    if not extractions:
        LOGGER.debug("No commitments extracted from Signal exchange")
        return

    LOGGER.info(
        "Extracted %s commitment(s) from Signal exchange with %s",
        len(extractions),
        sender,
    )

    # Create commitments
    for extraction in extractions:
        try:
            # Determine source based on confidence
            # User-initiated messages should have high confidence for user source
            # Agent suggestions should use agent source with lower confidence
            source = "user"  # Default to user-initiated
            confidence = extraction.get("confidence")

            # Remove confidence from payload since it's passed separately in the request
            # CommitmentCreationInput has extra="forbid" so it rejects unknown fields
            payload = {k: v for k, v in extraction.items() if k != "confidence"}

            # Note: Signal messages don't have artifacts in the object store,
            # so we don't link provenance (which requires an artifact to exist).
            # The commitment's metadata can still capture the Signal source if needed.

            # Create commitment request
            request = CommitmentCreationRequest(
                payload=payload,
                authority=source,
                confidence=confidence,
                source_context=CommitmentSourceContext(
                    source_actor=sender,
                    source_medium="message",
                    source_uri=None,
                    intake_channel="signal",
                ),
                provenance=None,  # No provenance for Signal-sourced commitments
            )

            # Attempt creation
            result = creation_service.create(request)

            # Handle result
            if isinstance(result, CommitmentCreationDedupeRequired):
                LOGGER.info(
                    "Commitment creation requires dedupe review: %s",
                    result.proposal,
                )
                if router is not None:
                    description = str(extraction.get("description", "")).strip()
                    route_creation_proposal_notification(
                        session_factory=session_factory,
                        router=router,
                        proposal_kind="dedupe",
                        creation_payload=extraction,
                        authority=source,
                        confidence=confidence,
                        source_context=request.source_context,
                        message=(
                            "Dedupe review needed for Signal commitment: "
                            f'"{description or "Unspecified commitment"}". '
                            f"Potential duplicate commitment_id={result.proposal.candidate.commitment_id} "
                            f"(confidence={result.proposal.confidence:.2f}, "
                            f"threshold={result.proposal.threshold:.2f})."
                        ),
                        context=ProposalRoutingContext(
                            scope="signal",
                            source_channel="signal",
                            source_actor=sender,
                            fingerprint_components=(
                                "dedupe",
                                sender,
                                timestamp.isoformat(),
                                description,
                                sha1(user_message.encode("utf-8")).hexdigest()[:12],
                            ),
                            provenance=[
                                ProvenanceInput(
                                    input_type="signal_sender",
                                    reference=sender,
                                    description="Signal sender that surfaced this proposal.",
                                )
                            ],
                        ),
                    )
            elif isinstance(result, CommitmentCreationApprovalRequired):
                LOGGER.info(
                    "Commitment creation requires approval: %s",
                    result.proposal,
                )
                if router is not None:
                    description = str(extraction.get("description", "")).strip()
                    route_creation_proposal_notification(
                        session_factory=session_factory,
                        router=router,
                        proposal_kind="approval",
                        creation_payload=extraction,
                        authority=source,
                        confidence=confidence,
                        source_context=request.source_context,
                        message=(
                            "Approval needed for Signal commitment creation: "
                            f'"{description or "Unspecified commitment"}". '
                            f"Source={result.proposal.source.value} "
                            f"(confidence={result.proposal.confidence:.2f}, "
                            f"threshold={result.proposal.threshold:.2f}). "
                            f"Reason={result.proposal.reason}."
                        ),
                        context=ProposalRoutingContext(
                            scope="signal",
                            source_channel="signal",
                            source_actor=sender,
                            fingerprint_components=(
                                "approval",
                                sender,
                                timestamp.isoformat(),
                                description,
                                sha1(user_message.encode("utf-8")).hexdigest()[:12],
                            ),
                            provenance=[
                                ProvenanceInput(
                                    input_type="signal_sender",
                                    reference=sender,
                                    description="Signal sender that surfaced this proposal.",
                                )
                            ],
                        ),
                    )
            else:
                LOGGER.info(
                    "Commitment created from Signal: commitment_id=%s description=%s sender=%s",
                    result.commitment.commitment_id,
                    result.commitment.description[:100],
                    sender,
                )
                # Record progress for successful creation
                if progress_service is not None and isinstance(result, CommitmentCreationSuccess):
                    try:
                        progress_service.record_progress(
                            commitment_id=result.commitment.commitment_id,
                            provenance_id=result.provenance_id,
                            occurred_at=timestamp,
                            summary="Commitment created from Signal message",
                            snippet=user_message[:200] if user_message else None,
                            metadata={"sender": sender, "intake_channel": "signal"},
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
                "Failed to create commitment from Signal extraction: %s",
                extraction.get("description", "unknown"),
            )


def create_signal_commitment_extractor(
    session_factory: Callable[[], Session],
    schedule_adapter: SchedulerAdapter,
    llm_client: LLMClient | None = None,
    router: AttentionRouter | None = None,
) -> Callable[[str, str, str, datetime], None]:
    """Create a Signal commitment extractor function.

    Args:
        session_factory: Factory for creating database sessions
        schedule_adapter: Scheduler adapter for miss detection scheduling
        llm_client: Optional LLM client for extraction

    Returns:
        A function that extracts and creates commitments from Signal exchanges
    """
    creation_service = CommitmentCreationService(
        session_factory,
        schedule_adapter,
        llm_client=llm_client,
    )
    progress_service = CommitmentProgressService(session_factory)
    resolved_router = router or AttentionRouter()

    def extractor(
        user_message: str,
        agent_response: str,
        sender: str,
        timestamp: datetime,
    ) -> None:
        """Extract and create commitments from a Signal message exchange."""
        extract_and_create_commitments_from_signal(
            user_message=user_message,
            agent_response=agent_response,
            sender=sender,
            timestamp=timestamp,
            session_factory=session_factory,
            creation_service=creation_service,
            llm_client=llm_client,
            progress_service=progress_service,
            router=resolved_router,
        )

    return extractor


__all__ = [
    "extract_and_create_commitments_from_signal",
    "create_signal_commitment_extractor",
]
