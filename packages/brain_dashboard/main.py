"""Entrypoint for the Brain Dashboard Textual app."""

from __future__ import annotations

from packages.brain_dashboard.app import BrainDashboardApp


def main() -> None:
    """Run the Brain Dashboard application."""
    BrainDashboardApp().run()


if __name__ == "__main__":
    main()
