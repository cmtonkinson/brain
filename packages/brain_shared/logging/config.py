"""Minimal stdout logging configuration for Brain services.

Design goals:
- Always emit logs to stdout for Docker/Compose log collection.
- Provide structured fields suitable for future OpenTelemetry correlation.
- Keep API simple while allowing later extension without breaking callers.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from .context import get_context
from . import fields


class ContextFilter(logging.Filter):
    """Inject per-request/service context into each log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        context = get_context()
        setattr(record, "context", context)
        for key, value in context.items():
            setattr(record, key, value)
        return True


class JsonFormatter(logging.Formatter):
    """Emit newline-delimited JSON logs with stable core fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            fields.TIMESTAMP: datetime.now(UTC).isoformat(),
            fields.LEVEL: record.levelname,
            fields.LOGGER: record.name,
            fields.MESSAGE: record.getMessage(),
        }

        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload.update(context)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, separators=(",", ":"))


class PlainFormatter(logging.Formatter):
    """Human-readable formatter that still appends structured context."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        context = getattr(record, "context", None)
        if not isinstance(context, dict) or not context:
            return message
        suffix = " ".join(f"{key}={value}" for key, value in sorted(context.items()))
        return f"{message} {suffix}"


def configure_logging(
    *,
    level: str = "INFO",
    json_output: bool = True,
    service: str | None = None,
    environment: str | None = None,
) -> None:
    """Configure root logging with a single stdout handler.

    This function is idempotent for handler setup: existing root handlers are
    replaced to avoid duplicate emissions when called multiple times.
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(level.upper())
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter() if json_output else PlainFormatter())

    root.addHandler(handler)
    root.propagate = False

    seed_context: dict[str, str] = {}
    if service:
        seed_context[fields.SERVICE] = service
    if environment:
        seed_context[fields.ENVIRONMENT] = environment
    if seed_context:
        from .context import bind_context

        bind_context(**seed_context)


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger using Python's standard logging hierarchy."""
    return logging.getLogger(name)
