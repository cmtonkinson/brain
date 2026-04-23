"""Dashboard header widget: compact 7-component health bar."""

from __future__ import annotations

from textual.widgets import Static

from lib.dashboard.data_sources.health import COMPONENTS, HealthAggregator
from lib.dashboard.models.health import ComponentHealth

_COMPONENT_ORDER = COMPONENTS
_STATE_TOKENS = {
    "ok": "[green]OK[/green]",
    "no": "[red]NO[/red]",
    "unknown": "[dim]??[/dim]",
}


def _render_health(components: list[ComponentHealth]) -> str:
    """Build compact health line from a list of ComponentHealth."""
    by_name = {c.name: c for c in components}
    parts = []
    for name in _COMPONENT_ORDER:
        health = by_name.get(name)
        state = health.state if health is not None else "unknown"
        token = _STATE_TOKENS.get(state, "[dim]??[/dim]")
        parts.append(f"{name} {token}")
    return "  ".join(parts)


class HealthHeader(Static):
    """Compact top-of-screen health bar backed by HealthAggregator."""

    def __init__(
        self,
        aggregator: HealthAggregator | None = None,
        _fixture: list[ComponentHealth] | None = None,
    ) -> None:
        super().__init__(id="health-header", markup=True)
        self._aggregator = aggregator
        self._fixture = _fixture  # for testing without live data

    def on_mount(self) -> None:
        self._refresh_health()
        self.set_interval(2.0, self._refresh_health)

    def _refresh_health(self) -> None:
        if self._fixture is not None:
            self.update(_render_health(self._fixture))
            return
        if self._aggregator is not None:
            snapshot = self._aggregator.get_snapshot()
            components: list[ComponentHealth] = snapshot.data or []
            self.update(_render_health(components))
        else:
            # No aggregator configured — show all unknown
            self.update(_render_health([]))
