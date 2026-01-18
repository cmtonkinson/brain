"""Attention router entry point for outbound notifications."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from attention.router_gate import activate_router_context, deactivate_router_context
from services.signal import SignalClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutboundSignal:
    """Outbound signal payload for routing."""

    source_component: str
    channel: str
    from_number: str
    to_number: str
    message: str


@dataclass(frozen=True)
class RoutingResult:
    """Result of routing an outbound signal."""

    decision: str
    channel: str | None


class AttentionRouter:
    """Attention router gate for outbound communication."""

    def __init__(self, signal_client: SignalClient | None = None) -> None:
        """Initialize the router with service clients."""
        self._signal_client = signal_client or SignalClient()
        self._routed: list[OutboundSignal] = []

    async def route_signal(self, signal: OutboundSignal) -> RoutingResult:
        """Route an outbound signal through the attention gate."""
        self._routed.append(signal)
        token = activate_router_context()
        try:
            if signal.channel == "signal":
                ok = await self._signal_client.send_message(
                    signal.from_number,
                    signal.to_number,
                    signal.message,
                    source_component=signal.source_component,
                )
                return RoutingResult(
                    decision="DELIVERED" if ok else "LOG_ONLY",
                    channel="signal" if ok else None,
                )
            logger.warning("Unsupported channel %s; defaulting to LOG_ONLY.", signal.channel)
            return RoutingResult(decision="LOG_ONLY", channel=None)
        finally:
            deactivate_router_context(token)

    def routed_signals(self) -> list[OutboundSignal]:
        """Return routed signals for testing and inspection."""
        return list(self._routed)
