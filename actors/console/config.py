"""Runtime configuration for the Console TUI."""

from __future__ import annotations

import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lib.shared.config import load_actor_settings, load_core_settings


class ConsoleConfig(BaseModel):
    """Console TUI connection and behavior settings.

    All fields are validated at construction time. ``preferred_timezone`` is
    always sourced from ``core.profile.preferred_timezone``; it is not
    overridable via a separate env var.
    """

    model_config = ConfigDict(frozen=True)

    host: str = "127.0.0.1"
    port: int = Field(default=8898, ge=1, le=65535)
    timeout_seconds: float = Field(default=60.0, gt=0)
    poll_timeout_seconds: float = Field(default=30.0, gt=0)
    poll_error_backoff_seconds: float = Field(default=1.0, gt=0)
    input_max_lines: int = Field(default=10, gt=0)
    input_history_size: int = Field(default=1000, gt=0)
    editor: str = "vim"
    preferred_timezone: str = "UTC"

    @field_validator("preferred_timezone")
    @classmethod
    def _validate_timezone(cls, v: str) -> str:
        """Raise at construction time if the timezone string is unrecognized."""
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, KeyError) as exc:
            raise ValueError(f"unrecognized timezone: {v!r}") from exc
        return v

    @property
    def tz(self) -> ZoneInfo:
        """Resolved ZoneInfo for the preferred timezone."""
        return ZoneInfo(self.preferred_timezone)


def load_console_config() -> ConsoleConfig:
    """Build console config from actors.yaml, core profile, and EDITOR env var."""
    actor_settings = load_actor_settings()
    core_settings = load_core_settings()
    return ConsoleConfig(
        host=actor_settings.core.host,
        port=actor_settings.core.port,
        timeout_seconds=actor_settings.core.timeout_seconds,
        poll_timeout_seconds=actor_settings.console.poll_timeout_seconds,
        poll_error_backoff_seconds=actor_settings.console.poll_error_backoff_seconds,
        input_max_lines=actor_settings.console.input_max_lines,
        input_history_size=actor_settings.console.input_history_size,
        editor=os.environ.get("EDITOR", actor_settings.console.editor),
        preferred_timezone=core_settings.profile.preferred_timezone,
    )
