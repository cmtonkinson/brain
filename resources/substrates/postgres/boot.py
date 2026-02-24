"""Boot hook for Postgres substrate readiness."""

from __future__ import annotations

from packages.brain_core.boot import BootContext
from resources.substrates.postgres.config import resolve_postgres_settings
from resources.substrates.postgres.engine import create_postgres_engine
from resources.substrates.postgres.health import ping

dependencies: tuple[str, ...] = tuple()


def is_ready(ctx: BootContext) -> bool:
    """Return true when Postgres can answer a basic query."""
    settings = resolve_postgres_settings(ctx.settings)
    engine = create_postgres_engine(settings)
    try:
        return ping(engine)
    finally:
        engine.dispose()


def boot(ctx: BootContext) -> None:
    """Execute no-op startup hook after readiness is confirmed."""
    del ctx
