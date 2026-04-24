"""Negative fixture: lower-tier component importing higher-tier module."""

from services.action.example.api import invoke


def call() -> None:
    """Trigger tier violation fixture."""
    invoke()
