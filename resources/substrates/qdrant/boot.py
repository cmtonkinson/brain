"""Boot hook for the Qdrant substrate; registers Qdrant-specific instrumentation."""

from __future__ import annotations

from lib.core.boot import BootContext
from lib.shared.logging import register_public_api_concern
from resources.substrates.qdrant.instrumentation import (
    qdrant_public_api_metrics_concern_factory,
)

register_public_api_concern(qdrant_public_api_metrics_concern_factory)

dependencies: tuple[str, ...] = tuple()


def is_ready(ctx: BootContext) -> bool:
    """Return immediate readiness for components without startup dependencies."""
    del ctx
    return True


def boot(ctx: BootContext) -> None:
    """Execute no-op startup hook for components without boot actions."""
    del ctx
