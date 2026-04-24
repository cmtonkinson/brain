"""Valkey client construction helpers."""

from __future__ import annotations

from valkey import Valkey

from resources.substrates.valkey.config import ValkeySettings


def create_valkey_client(settings: ValkeySettings) -> Valkey:
    """Construct a configured Valkey client instance."""
    return create_valkey_client_with_timeouts(
        settings=settings,
        connect_timeout_seconds=settings.connect_timeout_seconds,
        socket_timeout_seconds=settings.socket_timeout_seconds,
    )


def create_valkey_client_with_timeouts(
    *,
    settings: ValkeySettings,
    connect_timeout_seconds: float,
    socket_timeout_seconds: float,
) -> Valkey:
    """Construct a Valkey client instance with explicit timeout values."""
    assert settings.url, (
        "ValkeySettings.url must be resolved before client construction"
    )
    return Valkey.from_url(
        url=settings.url,
        socket_connect_timeout=connect_timeout_seconds,
        socket_timeout=socket_timeout_seconds,
        max_connections=settings.max_connections,
        decode_responses=True,
        encoding="utf-8",
    )
