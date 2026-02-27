"""Runtime configuration primitives for Brain SDK clients."""

from __future__ import annotations

from dataclasses import dataclass, field
import os

DEFAULT_TARGET = "127.0.0.1:50051"
DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class BrainSdkConfig:
    """Connection and metadata defaults for one Brain SDK client."""

    target: str = DEFAULT_TARGET
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    source: str = "cli"
    principal: str = "operator"
    use_tls: bool = False
    wait_for_ready: bool = False
    channel_options: tuple[tuple[str, str | int], ...] = field(default_factory=tuple)


def resolve_target(value: str | None = None) -> str:
    """Resolve one gRPC target from explicit value or process environment."""
    if value is not None and value.strip() != "":
        return value
    env_value = os.getenv("BRAIN_GRPC_TARGET", "").strip()
    return env_value if env_value != "" else DEFAULT_TARGET


def resolve_timeout_seconds(value: float | None = None) -> float:
    """Resolve one timeout value from explicit override or environment."""
    if value is not None:
        return value
    env_value = os.getenv("BRAIN_GRPC_TIMEOUT_SECONDS", "").strip()
    if env_value == "":
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return float(env_value)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
