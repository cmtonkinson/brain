"""Dashboard package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import BrainDashboardApp

__all__ = ["BrainDashboardApp"]


def __getattr__(name: str) -> object:
    if name == "BrainDashboardApp":
        from .app import BrainDashboardApp  # noqa: PLC0415

        return BrainDashboardApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
