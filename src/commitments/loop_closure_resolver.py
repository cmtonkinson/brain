"""Resolution logic for mapping loop-closure replies to commitments."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from models import Commitment

_EXPLICIT_REFERENCE_PATTERN = re.compile(r"^commitment\.[a-z_]+:(\d+)$")
_MESSAGE_REFERENCE_PATTERN = re.compile(r"\bcommitment\.[a-z_]+:(\d+)\b")
_RESOLVED_STATES = {"COMPLETED", "CANCELED"}


class LoopClosureReplyResolver:
    """Resolve target commitment IDs for loop-closure replies."""

    def resolve_commitment_id(
        self,
        session: Session,
        *,
        sender: str,
        message: str,
        signal_reference: str | None = None,
    ) -> int | None:
        """Resolve the most appropriate commitment ID for a loop-closure reply."""
        del sender  # Placeholder until commitment ownership is modeled.

        explicit_id = self._extract_reference_id(signal_reference)
        if explicit_id is not None and self._commitment_exists(session, explicit_id):
            return explicit_id

        for reference_id in self._extract_message_reference_ids(message):
            if self._commitment_exists(session, reference_id):
                return reference_id

        return self._latest_unresolved_commitment_id(session)

    @staticmethod
    def _extract_reference_id(reference: str | None) -> int | None:
        """Extract a commitment ID from a structured signal reference."""
        if reference is None:
            return None
        match = _EXPLICIT_REFERENCE_PATTERN.fullmatch(reference.strip())
        if match is None:
            return None
        return int(match.group(1))

    @staticmethod
    def _extract_message_reference_ids(message: str) -> list[int]:
        """Extract commitment reference IDs that appear in message text."""
        return [int(match.group(1)) for match in _MESSAGE_REFERENCE_PATTERN.finditer(message)]

    @staticmethod
    def _commitment_exists(session: Session, commitment_id: int) -> bool:
        """Return True when a commitment with the given ID exists."""
        return (
            session.query(Commitment.commitment_id)
            .filter(Commitment.commitment_id == commitment_id)
            .first()
            is not None
        )

    @staticmethod
    def _latest_unresolved_commitment_id(session: Session) -> int | None:
        """Return the most recently updated unresolved commitment ID, if any."""
        row = (
            session.query(Commitment.commitment_id)
            .filter(Commitment.state.notin_(_RESOLVED_STATES))
            .order_by(Commitment.updated_at.desc(), Commitment.commitment_id.desc())
            .first()
        )
        if row is None:
            return None
        return int(row.commitment_id)


__all__ = ["LoopClosureReplyResolver"]
