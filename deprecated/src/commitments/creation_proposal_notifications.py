"""Shared routing and persistence helpers for creation/dedupe proposals."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from hashlib import sha1
from typing import Callable, Iterable, Literal, Sequence

from sqlalchemy.orm import Session

from attention.envelope_schema import ProvenanceInput
from attention.router import AttentionRouter
from commitments.creation_proposal_repository import (
    CommitmentCreationProposalCreateInput,
    CommitmentCreationProposalRepository,
)
from commitments.creation_service import CommitmentSourceContext
from commitments.notifications import (
    CommitmentNotification,
    CommitmentNotificationType,
    submit_commitment_notification,
)

logger = logging.getLogger(__name__)

ProposalKind = Literal["dedupe", "approval"]


@dataclass(frozen=True)
class ProposalRoutingContext:
    """Proposal routing metadata shared across ingest and Signal extractions."""

    scope: str
    source_channel: str
    source_actor: str | None
    fingerprint_components: Sequence[str]
    provenance: Sequence[ProvenanceInput]


def build_proposal_ref(
    *, scope: str, proposal_kind: ProposalKind, components: Iterable[str]
) -> str:
    """Build a deterministic proposal_ref from stable components."""
    fingerprint = sha1("|".join(components).encode("utf-8")).hexdigest()[:16]
    return f"{scope}:{proposal_kind}:{fingerprint}"


def route_creation_proposal_notification(
    *,
    session_factory: Callable[[], Session],
    router: AttentionRouter,
    proposal_kind: ProposalKind,
    creation_payload: dict,
    authority: str,
    confidence: float | None,
    source_context: CommitmentSourceContext | None,
    message: str,
    context: ProposalRoutingContext,
) -> str:
    """Persist and route a creation proposal notification with a stable reference."""
    proposal_ref = build_proposal_ref(
        scope=context.scope,
        proposal_kind=proposal_kind,
        components=context.fingerprint_components,
    )

    payload = {
        "creation_payload": dict(creation_payload),
        "authority": authority,
        "confidence": confidence,
        "source_context": _serialize_source_context(source_context),
    }
    repo = CommitmentCreationProposalRepository(session_factory)
    repo.create_or_replace_pending(
        CommitmentCreationProposalCreateInput(
            proposal_ref=proposal_ref,
            proposal_kind=proposal_kind,
            payload=payload,
            source_channel=context.source_channel,
            source_actor=context.source_actor,
        )
    )

    notification_type = (
        CommitmentNotificationType.DEDUPE_PROPOSAL
        if proposal_kind == "dedupe"
        else CommitmentNotificationType.CREATION_APPROVAL_PROPOSAL
    )
    signal_type = (
        "commitment.dedupe_proposal"
        if proposal_kind == "dedupe"
        else "commitment.creation_approval_proposal"
    )
    resolved_provenance = [
        ProvenanceInput(
            input_type="proposal_ref",
            reference=proposal_ref,
            description="Stable proposal reference for reply-based decisions.",
        ),
        *context.provenance,
    ]
    notification = CommitmentNotification(
        commitment_id=None,
        notification_type=notification_type,
        message=f"{message} proposal_ref={proposal_ref}",
        channel=context.source_channel,
        signal_reference=f"{signal_type}:{proposal_ref}",
        provenance=resolved_provenance,
    )

    try:
        submit_commitment_notification(router, notification)
    except Exception:
        logger.exception(
            "Failed to route creation proposal notification: proposal_ref=%s type=%s",
            proposal_ref,
            notification.notification_type.value,
        )
    return proposal_ref


def _serialize_source_context(
    source_context: CommitmentSourceContext | None,
) -> dict[str, str | None] | None:
    """Serialize source context for JSON persistence."""
    if source_context is None:
        return None
    return {
        "source_actor": source_context.source_actor,
        "source_medium": source_context.source_medium,
        "source_uri": source_context.source_uri,
        "intake_channel": source_context.intake_channel,
    }


__all__ = [
    "ProposalRoutingContext",
    "build_proposal_ref",
    "route_creation_proposal_notification",
]
