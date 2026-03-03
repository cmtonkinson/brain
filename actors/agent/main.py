"""Stub runtime entrypoint for the long-lived Brain Agent container."""

from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path

from packages.brain_shared.config import load_actor_settings

_LOGGER = logging.getLogger(__name__)
_RUNNING = True


def _handle_shutdown(_signum: int, _frame: object) -> None:
    """Mark the stub runtime for graceful shutdown."""
    global _RUNNING
    _RUNNING = False


def _resolve_config_path() -> Path | None:
    """Return an explicit actors config path when the env override is set."""
    value = os.getenv("BRAIN_ACTORS_CONFIG_FILE", "").strip()
    if value == "":
        return None
    return Path(value)


def _configure_logging() -> None:
    """Install a minimal process-local logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    """Load actor runtime settings and hold the stub agent process open."""
    global _RUNNING
    _RUNNING = True

    _configure_logging()
    settings = load_actor_settings(config_path=_resolve_config_path())

    _LOGGER.info(
        "brain agent stub started",
        extra={
            "socket_path": settings.core.socket_path,
            "timeout_seconds": settings.core.timeout_seconds,
            "source": settings.agent.source,
            "principal": settings.agent.principal,
        },
    )

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)
    try:
        while _RUNNING:
            time.sleep(1.0)
    finally:
        _LOGGER.info("brain agent stub stopped")


if __name__ == "__main__":
    main()
