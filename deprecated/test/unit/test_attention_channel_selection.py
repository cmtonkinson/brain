"""Unit tests for attention channel selection."""

from __future__ import annotations

from attention.channel_selection import ChannelSelectionInputs, select_channel


def test_urgent_failure_selects_signal() -> None:
    """Ensure urgent failures select Signal as the primary channel."""
    result = select_channel(
        ChannelSelectionInputs(
            decision="NOTIFY",
            signal_type="task.failed",
            urgency_score=0.9,
            channel_cost=0.4,
            content_type="status",
        )
    )

    assert result.primary_channel == "signal"
    assert result.final_decision == "NOTIFY:signal"


def test_long_form_analysis_selects_obsidian() -> None:
    """Ensure long-form analysis defaults to Signal while other channels are unavailable."""
    result = select_channel(
        ChannelSelectionInputs(
            decision="NOTIFY",
            signal_type="analysis.report",
            urgency_score=0.4,
            channel_cost=0.2,
            content_type="analysis",
        )
    )

    assert result.primary_channel == "signal"
    assert result.final_decision == "NOTIFY:signal"


def test_unknown_channel_falls_back_to_log_only() -> None:
    """Ensure unknown channel requests fall back to LOG_ONLY."""
    result = select_channel(
        ChannelSelectionInputs(
            decision="NOTIFY:pagerduty",
            signal_type="task.failed",
            urgency_score=0.9,
            channel_cost=0.4,
            content_type="status",
        )
    )

    assert result.final_decision == "LOG_ONLY"
    assert result.primary_channel is None
