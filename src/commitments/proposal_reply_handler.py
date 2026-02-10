"""Handler for decision replies to creation and dedupe proposals."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal

from sqlalchemy.orm import Session

from commitments.creation_service import (
    CommitmentCreationRequest,
    CommitmentCreationService,
    CommitmentSourceContext,
    CommitmentCreationSuccess,
)
from commitments.creation_proposal_repository import CommitmentCreationProposalRepository
from scheduler.adapter_interface import SchedulerAdapter


@dataclass(frozen=True)
class ProposalReplyResult:
    """Outcome of processing a proposal reply message."""

    status: Literal["created", "approved_noop", "rejected"]
    proposal_ref: str
    proposal_kind: Literal["dedupe", "approval"]
    commitment_id: int | None = None


class CommitmentProposalReplyHandler:
    """Resolve proposal references from replies and apply operator decisions."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        schedule_adapter: SchedulerAdapter,
    ) -> None:
        """Initialize the reply handler with creation and proposal repositories."""
        self._creation_service = CommitmentCreationService(session_factory, schedule_adapter)
        self._proposal_repo = CommitmentCreationProposalRepository(session_factory)

    def try_handle_reply(
        self,
        sender: str,
        message: str,
        timestamp: datetime | None = None,
    ) -> ProposalReplyResult | None:
        """Attempt to apply a proposal decision from a Signal reply message."""
        timestamp = timestamp or datetime.now(timezone.utc)
        proposal_ref = _extract_proposal_ref(message)
        if proposal_ref is None:
            return None

        proposal = self._proposal_repo.get_pending(proposal_ref)
        if proposal is None:
            return None

        decision = _parse_decision(message, proposal_kind=str(proposal.proposal_kind))
        if decision is None:
            return None

        if decision == "reject":
            self._proposal_repo.mark_rejected(
                proposal_ref,
                decided_by=sender,
                decided_at=timestamp,
                reason="user_reply_rejected",
            )
            return ProposalReplyResult(
                status="rejected",
                proposal_ref=proposal_ref,
                proposal_kind=str(proposal.proposal_kind),
                commitment_id=None,
            )

        if decision == "approve_existing":
            self._proposal_repo.mark_approved(
                proposal_ref,
                decided_by=sender,
                created_commitment_id=None,
                decided_at=timestamp,
                reason="user_reply_keep_existing",
            )
            return ProposalReplyResult(
                status="approved_noop",
                proposal_ref=proposal_ref,
                proposal_kind=str(proposal.proposal_kind),
                commitment_id=None,
            )

        payload = proposal.payload or {}
        creation_payload = payload.get("creation_payload")
        if not isinstance(creation_payload, dict):
            raise ValueError(f"Invalid creation proposal payload for {proposal_ref}.")

        source_context = _deserialize_source_context(payload.get("source_context"))
        authority = str(payload.get("authority") or "user")
        confidence = payload.get("confidence")
        confidence_value = float(confidence) if isinstance(confidence, (int, float)) else None

        create_result = self._creation_service.create(
            CommitmentCreationRequest(
                payload=creation_payload,
                authority=authority,
                confidence=confidence_value,
                source_context=source_context,
                bypass_dedupe_once=str(proposal.proposal_kind) == "dedupe",
            )
        )
        commitment_id = (
            create_result.commitment.commitment_id
            if isinstance(create_result, CommitmentCreationSuccess)
            else None
        )
        self._proposal_repo.mark_approved(
            proposal_ref,
            decided_by=sender,
            created_commitment_id=commitment_id,
            decided_at=timestamp,
            reason="user_reply_approved",
        )
        return ProposalReplyResult(
            status="created" if commitment_id is not None else "approved_noop",
            proposal_ref=proposal_ref,
            proposal_kind=str(proposal.proposal_kind),
            commitment_id=commitment_id,
        )


_APPROVE_KEYWORDS = ("approve", "yes", "ok", "okay", "create")
_REJECT_KEYWORDS = ("reject", "no", "skip", "ignore", "cancel")
_NEW_KEYWORDS = ("new", "not duplicate", "not a duplicate", "keep both")
_EXISTING_KEYWORDS = ("duplicate", "existing", "same", "merge")


def _extract_proposal_ref(message: str) -> str | None:
    """Extract proposal_ref tokens from inbound messages."""
    explicit_match = re.search(r"proposal_ref\s*[:=]\s*([A-Za-z0-9:_-]+)", message)
    if explicit_match is not None:
        return explicit_match.group(1)
    inline_match = re.search(r"\b(?:ingest|signal):(?:dedupe|approval):[A-Fa-f0-9]{16}\b", message)
    if inline_match is not None:
        return inline_match.group(0)
    return None


def _parse_decision(
    message: str,
    *,
    proposal_kind: str,
) -> Literal["approve_create", "approve_existing", "reject"] | None:
    """Parse operator decision keywords from free-form proposal replies."""
    normalized = message.lower().replace("’", "'").strip()
    if proposal_kind == "dedupe":
        if any(keyword in normalized for keyword in _NEW_KEYWORDS):
            return "approve_create"
        if any(keyword in normalized for keyword in _EXISTING_KEYWORDS):
            return "approve_existing"

    if any(keyword in normalized for keyword in _REJECT_KEYWORDS):
        return "reject"
    if any(keyword in normalized for keyword in _APPROVE_KEYWORDS):
        return "approve_create"
    return None


def _deserialize_source_context(value: object) -> CommitmentSourceContext | None:
    """Convert serialized source context payloads back into typed input."""
    if not isinstance(value, dict):
        return None

    intake_channel = value.get("intake_channel")
    if intake_channel not in {"signal", "ingest", None}:
        intake_channel = None

    return CommitmentSourceContext(
        source_actor=_coerce_optional_str(value.get("source_actor")),
        source_medium=_coerce_optional_str(value.get("source_medium")),
        source_uri=_coerce_optional_str(value.get("source_uri")),
        intake_channel=intake_channel,
    )


def _coerce_optional_str(value: object) -> str | None:
    """Normalize unknown values into optional strings."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


__all__ = ["CommitmentProposalReplyHandler", "ProposalReplyResult"]
