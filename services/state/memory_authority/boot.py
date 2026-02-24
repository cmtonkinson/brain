"""Default no-op boot hook for component startup orchestration."""

from __future__ import annotations

from packages.brain_core.boot import BootContext

dependencies: tuple[str, ...] = ("substrate_postgres",)


def is_ready(ctx: BootContext) -> bool:
    """Return immediate readiness for components without startup dependencies."""
    del ctx
    return True


def boot(ctx: BootContext) -> None:
    """Execute no-op startup hook for components without boot actions."""
    del ctx
