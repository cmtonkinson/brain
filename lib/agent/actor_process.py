"""Shared process-level helpers for long-running actor entrypoints."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from lib.sdk.config import BrainSdkConfig
from lib.shared import logging as shared_logging


def resolve_env_path(*, env_var: str, default: Path) -> Path:
    """Return an env-var path override or the provided default path."""
    value = os.getenv(env_var, "").strip()
    return Path(value) if value else default


def touch_path(path: Path) -> None:
    """Create parent directories and touch one marker file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def configure_actor_logging(*, settings: Any, default_process_name: str) -> None:
    """Configure shared logging from actor settings."""
    process_name = settings.logging.process_name or default_process_name
    shared_logging.configure_logging(
        level=str(settings.logging.level),
        file_capture_enabled=settings.logging.file_capture_enabled,
        file_capture_level=str(settings.logging.file_capture_level),
        file_capture_directory=settings.logging.file_capture_directory,
        json_output=bool(settings.logging.json_output),
        process_name=process_name,
        environment=str(settings.logging.environment),
    )


def sdk_config_from_parts(
    *, core_settings: Any, source: str, principal: str
) -> BrainSdkConfig:
    """Build a Brain SDK config from actor and Core connection settings."""
    return BrainSdkConfig(
        host=core_settings.host,
        port=core_settings.port,
        timeout_seconds=core_settings.timeout_seconds,
        source=source,
        principal=principal,
    )


__all__ = [
    "configure_actor_logging",
    "resolve_env_path",
    "sdk_config_from_parts",
    "touch_path",
]
