"""Channel selection logic for attention routing decisions."""

from __future__ import annotations

from dataclasses import dataclass

from attention.assessment_engine import HIGH_URGENCY

ALLOWED_CHANNELS = {"signal", "obsidian", "digest", "web"}


@dataclass(frozen=True)
class ChannelSelectionInputs:
    """Inputs required to select a notification channel."""

    decision: str
    signal_type: str
    urgency_score: float
    channel_cost: float
    content_type: str
    record_to_obsidian: bool = False


@dataclass(frozen=True)
class ChannelSelectionResult:
    """Selected channels for a routing decision."""

    final_decision: str
    primary_channel: str | None
    secondary_channel: str | None


def select_channel(inputs: ChannelSelectionInputs) -> ChannelSelectionResult:
    """Select primary and optional secondary channels for notification."""
    decision_type, requested_channel = _parse_decision(inputs.decision)
    if decision_type not in {"NOTIFY", "ESCALATE"}:
        return ChannelSelectionResult(
            final_decision=inputs.decision,
            primary_channel=None,
            secondary_channel=None,
        )

    if requested_channel and requested_channel not in ALLOWED_CHANNELS:
        return ChannelSelectionResult(
            final_decision="LOG_ONLY",
            primary_channel=None,
            secondary_channel=None,
        )

    primary = requested_channel or _select_primary(inputs)
    if primary not in ALLOWED_CHANNELS:
        return ChannelSelectionResult(
            final_decision="LOG_ONLY",
            primary_channel=None,
            secondary_channel=None,
        )

    secondary = "obsidian" if inputs.record_to_obsidian else None
    return ChannelSelectionResult(
        final_decision=f"{decision_type}:{primary}",
        primary_channel=primary,
        secondary_channel=secondary,
    )


def _parse_decision(decision: str) -> tuple[str, str | None]:
    """Parse a decision string into type and optional channel."""
    if ":" in decision:
        prefix, channel = decision.split(":", 1)
        return prefix, channel
    return decision, None


def _select_primary(inputs: ChannelSelectionInputs) -> str:
    """Select a primary channel based on urgency and content semantics."""
    if inputs.content_type == "analysis":
        return "obsidian"
    if inputs.signal_type.endswith("failed") or inputs.urgency_score >= HIGH_URGENCY:
        return "signal"
    if inputs.channel_cost >= 0.7:
        return "digest"
    return "web"
