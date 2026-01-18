"""Runtime guards for non-skill entrypoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntrypointContext:
    """Context payload for non-skill entrypoints."""

    entrypoint: str
    actor: str | None
    channel: str | None


class EntrypointContextError(ValueError):
    """Raised when an entrypoint context is missing required fields."""


def require_entrypoint_context(context: EntrypointContext) -> None:
    """Raise when an entrypoint context lacks actor or channel values."""
    if context.actor is None or context.actor.strip() == "":
        raise EntrypointContextError(f"entrypoint {context.entrypoint} missing actor context")
    if context.channel is None or context.channel.strip() == "":
        raise EntrypointContextError(f"entrypoint {context.entrypoint} missing channel context")
