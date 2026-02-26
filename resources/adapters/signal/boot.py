"""Boot hook for Signal adapter container readiness."""

from __future__ import annotations

from packages.brain_core.boot import BootContext
from packages.brain_shared.http import (
    HttpClient,
    HttpJsonDecodeError,
    HttpRequestError,
    HttpStatusError,
)
from resources.adapters.signal.config import resolve_signal_adapter_settings
from resources.adapters.signal.constants import SIGNAL_HEALTH_PATH

dependencies: tuple[str, ...] = tuple()


def is_ready(ctx: BootContext) -> bool:
    """Return true when the Signal container health endpoint responds successfully."""
    settings = resolve_signal_adapter_settings(ctx.settings)
    client = HttpClient(
        base_url=settings.base_url.rstrip("/"),
        timeout_seconds=settings.health_timeout_seconds,
    )
    try:
        client.get(SIGNAL_HEALTH_PATH)
        return True
    except (HttpRequestError, HttpStatusError, HttpJsonDecodeError):
        return False
    finally:
        client.close()


def boot(ctx: BootContext) -> None:
    """Execute no-op startup hook after readiness is confirmed."""
    del ctx
