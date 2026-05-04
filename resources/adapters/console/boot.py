"""Boot hook for Console adapter local readiness."""

from __future__ import annotations

from lib.core.boot import BootContext

dependencies: tuple[str, ...] = tuple()


def is_ready(ctx: BootContext) -> bool:
    """Return true once the in-process adapter component exists."""
    del ctx
    return True


def boot(ctx: BootContext) -> None:
    """Execute no-op startup hook after readiness is confirmed."""
    del ctx
