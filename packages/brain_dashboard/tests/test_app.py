"""Smoke tests for the Brain Dashboard Textual app."""

from __future__ import annotations

from packages.brain_dashboard.app import BrainDashboardApp
from packages.brain_dashboard.widgets import HealthHeader, KeymapFooter
from packages.brain_dashboard.workspace import Workspace


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
