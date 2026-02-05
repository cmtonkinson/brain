"""Commitment extraction from Signal message exchanges."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from commitments.creation_service import (
    CommitmentCreationApprovalRequired,
    CommitmentCreationDedupeRequired,
    CommitmentCreationRequest,
    CommitmentCreationService,
    CommitmentProvenanceLinkInput,
)
from commitments.extraction import extract_commitments_from_text
from ingestion.provenance import ProvenanceSourceInput
from llm import LLMClient
from scheduler.adapter_interface import SchedulerAdapter

LOGGER = logging.getLogger(__name__)


def extract_and_create_commitments_from_signal(
    user_message: str,
    agent_response: str,
    sender: str,
    timestamp: datetime,
    creation_service: CommitmentCreationService,
    llm_client: LLMClient | None = None,
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
            # Build provenance for Signal message
            provenance_sources = [
                ProvenanceSourceInput(
                    source_type="signal",
                    source_uri=f"signal://{sender}",
                    source_actor=sender,
                    captured_at=timestamp,
                )
            ]

            # Create a synthetic object key for the Signal exchange
            # (not stored in object store, just for provenance linking)
            object_key = f"signal:{sender}:{timestamp.isoformat()}"

            provenance_link = CommitmentProvenanceLinkInput(
                object_key=object_key,
                ingestion_id=UUID("00000000-0000-0000-0000-000000000000"),  # Sentinel for Signal
                sources=provenance_sources,
            )

            # Determine source based on confidence
            # User-initiated messages should have high confidence for user source
            # Agent suggestions should use agent source with lower confidence
            source = "user"  # Default to user-initiated
            confidence = extraction.get("confidence")

            # Create commitment request
            request = CommitmentCreationRequest(
                payload=extraction,
                source=source,
                confidence=confidence,
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
                # TODO: Route dedupe proposal to attention router
            elif isinstance(result, CommitmentCreationApprovalRequired):
                LOGGER.info(
                    "Commitment creation requires approval: %s",
                    result.proposal,
                )
                # TODO: Route approval proposal to attention router
            else:
                LOGGER.info(
                    "Commitment created from Signal: commitment_id=%s description=%s sender=%s",
                    result.commitment.commitment_id,
                    result.commitment.description[:100],
                    sender,
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
            creation_service=creation_service,
            llm_client=llm_client,
        )

    return extractor


__all__ = [
    "extract_and_create_commitments_from_signal",
    "create_signal_commitment_extractor",
]
