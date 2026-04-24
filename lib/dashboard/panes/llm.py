"""LLM pane: provider/model recent-rate pressure summary."""

from __future__ import annotations

from typing import Protocol

from textual.app import ComposeResult
from textual.widgets import Static

from lib.dashboard.models.llm import LLMUsageRowView, LLMUsageTableView
from lib.dashboard.panes.base import BaseView

_REFRESH_INTERVAL = 2.0


class LLMUsageDataSource(Protocol):
    """Minimal LLM-usage contract consumed by the LLM pane."""

    def get_current(self) -> LLMUsageTableView | None:
        """Return the latest normalized LLM usage table."""


def _truncate(value: str, width: int) -> str:
    """Trim a string to a fixed-width cell with ellipsis when needed."""

    if len(value) <= width:
        return value.ljust(width)
    return f"{value[: max(1, width - 1)]}…"


def _format_rate(value: float | None) -> str:
    """Render a compact numeric rate while preserving zero as real data."""

    if value is None:
        return "?"
    if value >= 100:
        return f"{value:.0f}"
    if value >= 10:
        return f"{value:.1f}"
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _format_headroom(row: LLMUsageRowView) -> str:
    """Render the most relevant headroom signal for one usage row."""

    if (
        row.allowance_tokens_per_minute is not None
        and row.allowance_tokens_per_minute > 0
        and row.headroom_tokens_per_minute is not None
    ):
        pct = max(
            0.0,
            min(
                999.0,
                row.headroom_tokens_per_minute / row.allowance_tokens_per_minute * 100,
            ),
        )
        return f"tok {pct:.0f}%"

    if (
        row.allowance_requests_per_minute is not None
        and row.allowance_requests_per_minute > 0
        and row.headroom_requests_per_minute is not None
    ):
        pct = max(
            0.0,
            min(
                999.0,
                row.headroom_requests_per_minute
                / row.allowance_requests_per_minute
                * 100,
            ),
        )
        return f"req {pct:.0f}%"

    if (
        row.allowance_requests_per_minute is None
        and row.allowance_tokens_per_minute is None
    ):
        return "n/a"

    return "unknown"


class LLMPane(BaseView):
    """Compact table summarizing recent provider/model rate pressure."""

    view_id = "llm"
    view_title = "LLM"

    DEFAULT_CSS = """
    LLMPane { layout: vertical; height: 1fr; }
    LLMPane > #llm-body { height: 1fr; }
    """

    def __init__(
        self,
        usage_source: LLMUsageDataSource | None = None,
        usage: LLMUsageTableView | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._usage_source = usage_source
        self._usage = usage

    def compose(self) -> ComposeResult:
        yield Static(self._render_body(), id="llm-body")

    def on_mount(self) -> None:
        self.set_interval(_REFRESH_INTERVAL, self._refresh_from_source)

    def _refresh_from_source(self) -> None:
        if self._usage_source is None:
            return
        usage = self._usage_source.get_current()
        if usage is None:
            return
        self.refresh_data(usage)

    def refresh_data(self, usage: LLMUsageTableView | None) -> None:
        """Replace pane data and refresh the mounted content widget."""

        self._usage = usage
        try:
            self.query_one("#llm-body", Static).update(self._render_body())
        except Exception:
            pass

    def _render_body(self) -> str:
        if self._usage is None or not self._usage.rows:
            return "LLM\n—"

        lines = [
            "LLM",
            "",
            "Provider   Model                  Req/s  Tok/s  Req/m  Tok/m  Headroom   State",
        ]
        for row in self._usage.rows:
            lines.append(
                "  ".join(
                    [
                        _truncate(row.provider, 10),
                        _truncate(row.model, 22),
                        _format_rate(row.request_rate_5s).rjust(5),
                        _format_rate(row.token_rate_5s).rjust(5),
                        _format_rate(row.request_rate_60s).rjust(5),
                        _format_rate(row.token_rate_60s).rjust(5),
                        _truncate(_format_headroom(row), 10),
                        row.pressure_state,
                    ]
                )
            )
        return "\n".join(lines)
