"""Negative fixture: external import into a service-private module."""

from services.state.example.internal.repo import Repo


def use_repo() -> Repo:
    """Return a private dependency reference."""
    return Repo()
