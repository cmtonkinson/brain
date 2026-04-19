"""Runtime configuration for the Console TUI."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConsoleConfig:
    """Console TUI connection and behavior settings."""

    host: str = "127.0.0.1"
    port: int = 8898
    timeout_seconds: float = 60.0
    poll_timeout_seconds: float = 30.0
    editor: str = "vim"


def load_console_config() -> ConsoleConfig:
    """Build console config from environment variables with sane defaults."""
    return ConsoleConfig(
        host=os.environ.get("BRAIN_HOST", "127.0.0.1"),
        port=int(os.environ.get("BRAIN_PORT", "8898")),
        timeout_seconds=float(os.environ.get("BRAIN_TIMEOUT_SECONDS", "60.0")),
        poll_timeout_seconds=float(
            os.environ.get("BRAIN_CONSOLE_POLL_TIMEOUT_SECONDS", "30.0")
        ),
        editor=os.environ.get("EDITOR", "vim"),
    )
