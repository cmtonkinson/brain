"""Runtime configuration primitives for Brain SDK clients."""

from __future__ import annotations

from dataclasses import dataclass
import os

DEFAULT_SOCKET_PATH = "/app/config/generated/brain.sock"
DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class BrainSdkConfig:
    """Connection and metadata defaults for one Brain SDK client."""

    socket_path: str = DEFAULT_SOCKET_PATH
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    source: str = "cli"
    principal: str = "operator"


def resolve_socket_path(value: str | None = None) -> str:
    """Resolve one UDS socket path from explicit value or process environment."""
    if value is not None and value.strip() != "":
        return value
    env_value = os.getenv("BRAIN_SOCKET_PATH", "").strip()
    return env_value if env_value != "" else DEFAULT_SOCKET_PATH


def resolve_timeout_seconds(value: float | None = None) -> float:
    """Resolve one timeout value from explicit override or environment."""
    if value is not None:
        return value
    env_value = os.getenv("BRAIN_TIMEOUT_SECONDS", "").strip()
    if env_value == "":
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return float(env_value)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
