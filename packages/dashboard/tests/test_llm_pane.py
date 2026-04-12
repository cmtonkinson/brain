"""Tests for LLMPane rendering logic."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from packages.dashboard.models.llm import LLMUsageRowView, LLMUsageTableView
from packages.dashboard.panes.llm import LLMPane, _format_headroom


def _row(**kwargs) -> LLMUsageRowView:
    defaults = dict(
        provider="openai",
        model="gpt-5.4",
        request_count=8,
        token_count=55200,
        request_rate_5s=0.8,
        request_rate_60s=46.0,
        request_rate_10m=38.0,
        token_rate_5s=920.0,
        token_rate_60s=55200.0,
        token_rate_10m=44100.0,
        allowance_requests_per_minute=60.0,
        allowance_tokens_per_minute=67500.0,
        headroom_requests_per_minute=14.0,
        headroom_tokens_per_minute=12150.0,
        pressure_state="projected_breach",
        sampled_at=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return LLMUsageRowView(**defaults)


def test_llm_pane_no_data_renders_dash() -> None:
    pane = LLMPane()
    assert pane._render_body() == "LLM\n—"


def test_llm_pane_renders_usage_rows() -> None:
    pane = LLMPane(usage=LLMUsageTableView(rows=(_row(),)))
    text = pane._render_body()
    assert "Provider   Model" in text
    assert "openai" in text
    assert "gpt-5.4" in text
    assert "projected_breach" in text
    assert "tok 18%" in text


def test_llm_pane_preserves_zero_activity_as_data() -> None:
    pane = LLMPane(
        usage=LLMUsageTableView(
            rows=(
                _row(
                    provider="ollama",
                    model="qwen3:14b",
                    request_rate_5s=0.0,
                    request_rate_60s=0.0,
                    token_rate_5s=0.0,
                    token_rate_60s=0.0,
                    allowance_requests_per_minute=None,
                    allowance_tokens_per_minute=None,
                    headroom_requests_per_minute=None,
                    headroom_tokens_per_minute=None,
                    pressure_state="unknown",
                ),
            )
        )
    )
    text = pane._render_body()
    assert "ollama" in text
    assert "qwen3:14b" in text
    assert "  0" in text
    assert "n/a" in text


def test_format_headroom_returns_unknown_when_allowance_is_partial() -> None:
    assert (
        _format_headroom(
            _row(
                allowance_tokens_per_minute=1000.0,
                headroom_tokens_per_minute=None,
                allowance_requests_per_minute=None,
                headroom_requests_per_minute=None,
            )
        )
        == "unknown"
    )


def test_llm_usage_model_rejects_negative_counts() -> None:
    with pytest.raises(Exception):
        _row(request_count=-1)
