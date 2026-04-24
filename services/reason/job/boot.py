"""Boot hook for Job Service startup orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.core.boot import BootContext

dependencies: tuple[str, ...] = ("substrate_postgres",)


def is_ready(ctx: BootContext) -> bool:
    """Job Service is ready once Postgres is available."""
    del ctx
    return True


def boot(ctx: BootContext) -> None:
    """No-op boot; schema migrations handle setup."""
    del ctx
