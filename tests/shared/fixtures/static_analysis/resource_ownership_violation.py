"""Negative fixture: service importing an owned resource it does not own."""

from resources.substrates.secret_store.client import SecretClient


def build_client() -> SecretClient:
    """Return owned-resource client."""
    return SecretClient()
