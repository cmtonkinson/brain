"""Smoke tests for the dashboard Textual app."""

from __future__ import annotations

from packages.dashboard.app import BrainDashboardApp
from packages.dashboard.widgets import HealthHeader, KeymapFooter
from packages.dashboard.workspace import Workspace


def test_app_compose_contains_core_widgets() -> None:
    """Dashboard app should mount header, workspace, and footer widgets."""
    app = BrainDashboardApp()

    async def _exercise() -> None:
        async with app.run_test() as pilot:
            del pilot
            assert app.query_one(HealthHeader) is not None
            assert app.query_one(Workspace) is not None
            assert app.query_one(KeymapFooter) is not None

    import asyncio

    asyncio.run(_exercise())


def test_app_has_canonical_bindings() -> None:
    """App should have the canonical Phase 3 action bindings."""
    binding_keys = {b.key for b in BrainDashboardApp.BINDINGS}
    assert "s" in binding_keys  # split_horizontal
    assert "v" in binding_keys  # split_vertical
    assert "tab" in binding_keys  # focus_next
    assert "enter" in binding_keys  # maximize
    assert "Q" in binding_keys  # quit
    assert "1" in binding_keys  # load trace
    assert "2" in binding_keys  # load turn
    assert "3" in binding_keys  # load policy
    assert "4" in binding_keys  # load log
