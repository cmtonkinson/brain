"""Handler for loop-closure reply detection and processing."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from commitments.loop_closure_actions import (
    LoopClosureActionRequest,
    LoopClosureActionResult,
    LoopClosureActionService,
)
from commitments.loop_closure_parser import parse_loop_closure_response
from commitments.loop_closure_resolver import LoopClosureReplyResolver
from scheduler.adapter_interface import SchedulerAdapter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoopClosureReplyContext:
    """Context for a potential loop-closure reply."""

    sender: str
    message: str
    timestamp: datetime
    commitment_id: int | None = None


def detect_loop_closure_reply(
    session: Session,
    sender: str,
    message: str,
    *,
    signal_reference: str | None = None,
    resolver: LoopClosureReplyResolver | None = None,
) -> LoopClosureReplyContext | None:
    """Detect if a message is a potential loop-closure reply.

    This function checks if:
    1. The message contains a parseable loop-closure intent (complete, cancel, renegotiate)
    2. The message can be mapped to a target commitment

    Args:
        session: Database session
        sender: Phone number of message sender
        message: Message text
        signal_reference: Optional signal reference for deterministic linkage
        resolver: Optional commitment resolver override

    Returns:
        LoopClosureReplyContext if this appears to be a loop-closure reply, None otherwise
    """
    # Try parsing the message as a loop-closure response
    intent = parse_loop_closure_response(message)
    if intent is None:
        return None

    active_resolver = resolver or LoopClosureReplyResolver()
    commitment_id = active_resolver.resolve_commitment_id(
        session,
        sender=sender,
        message=message,
        signal_reference=signal_reference,
    )
    if commitment_id is None:
        logger.debug(
            "Loop-closure intent detected but no target commitment could be resolved for sender %s",
            sender,
        )
        return None

    return LoopClosureReplyContext(
        sender=sender,
        message=message,
        timestamp=datetime.now(timezone.utc),
        commitment_id=commitment_id,
    )


class LoopClosureReplyHandler:
    """Handler for processing loop-closure replies from Signal."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        schedule_adapter: SchedulerAdapter,
        *,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the loop-closure reply handler."""
        self._session_factory = session_factory
        self._action_service = LoopClosureActionService(
            session_factory,
            schedule_adapter,
            now_provider=now_provider,
        )

    def try_handle_reply(
        self,
        sender: str,
        message: str,
        timestamp: datetime | None = None,
        signal_reference: str | None = None,
    ) -> LoopClosureActionResult | None:
        """Attempt to handle a message as a loop-closure reply.

        Args:
            sender: Phone number of message sender
            message: Message text
            timestamp: Message timestamp (defaults to now)
            signal_reference: Optional signal reference from routing metadata

        Returns:
            LoopClosureActionResult if handled, None if not a loop-closure reply
        """
        timestamp = timestamp or datetime.now(timezone.utc)

        with self._session_factory() as session:
            # Detect if this is a loop-closure reply
            context = detect_loop_closure_reply(
                session,
                sender,
                message,
                signal_reference=signal_reference,
            )
            if context is None:
                return None

            # Parse the intent
            intent = parse_loop_closure_response(message)
            if intent is None:
                logger.warning(
                    "Loop-closure reply context detected but intent parsing failed for message: %s",
                    message,
                )
                return None

            # Build action request
            request = LoopClosureActionRequest(
                commitment_id=context.commitment_id,
                intent=intent,
                prompt="",  # We don't have the original prompt in this context
                response=message,
                actor="user",
                reason=f"User reply via Signal at {timestamp.isoformat()}",
            )

            # Apply the action
            try:
                result = self._action_service.apply_intent(request)
                logger.info(
                    "Processed loop-closure reply from %s for commitment %s: %s",
                    sender,
                    context.commitment_id,
                    result.status,
                )
                return result
            except Exception:
                logger.exception(
                    "Failed to apply loop-closure intent for commitment %s",
                    context.commitment_id,
                )
                return None


__all__ = [
    "LoopClosureReplyContext",
    "LoopClosureReplyHandler",
    "detect_loop_closure_reply",
]
