"""Negative fixture: lower-layer component importing higher-layer module."""

from services.action.example.api import invoke


def call() -> None:
    """Trigger layer violation fixture."""
    invoke()
