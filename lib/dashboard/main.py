"""Entrypoint for the dashboard Textual app."""

from __future__ import annotations

from lib.dashboard.app import BrainDashboardApp


def main() -> None:
    """Run the dashboard application."""
    BrainDashboardApp().run()


if __name__ == "__main__":
    main()
