"""Runtime configuration primitives for Brain SDK clients."""

from __future__ import annotations

from dataclasses import dataclass
import os

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8898
DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class BrainSdkConfig:
    """Connection and metadata defaults for one Brain SDK client."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    source: str = "cli"
    principal: str = "operator"


def resolve_host(value: str | None = None) -> str:
    """Resolve one SDK host from explicit value or process environment."""
    if value is not None and value.strip() != "":
        return value.strip()
    env_value = os.getenv("BRAIN_HOST", "").strip()
    if env_value != "":
        return env_value
    return DEFAULT_HOST


def resolve_port(value: int | None = None) -> int:
    """Resolve one SDK port from explicit override or process environment."""
    if value is not None:
        return value
    env_value = os.getenv("BRAIN_PORT", "").strip()
    if env_value == "":
        return DEFAULT_PORT
    try:
        port = int(env_value)
    except ValueError:
        return DEFAULT_PORT
    if port < 1 or port > 65535:
        return DEFAULT_PORT
    return port


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
