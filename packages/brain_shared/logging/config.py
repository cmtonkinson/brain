"""Minimal logging configuration for Brain services.

Design goals:
- Always emit logs to stdout for Docker/Compose log collection.
- Optionally emit a lower-threshold local file capture alongside stdout.
- Provide structured fields suitable for future OpenTelemetry correlation.
- Keep API simple while allowing later extension without breaking callers.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .context import get_context
from . import fields

VERBOSE = 5


def _register_verbose_level() -> None:
    """Register the custom ``VERBOSE`` level and logger method once."""
    if getattr(logging, "VERBOSE", None) != VERBOSE:
        logging.addLevelName(VERBOSE, "VERBOSE")
        setattr(logging, "VERBOSE", VERBOSE)

    if hasattr(logging.Logger, "verbose"):
        return

    def verbose(
        self: logging.Logger, msg: object, *args: object, **kwargs: object
    ) -> None:
        """Log one message at the custom ``VERBOSE`` level."""
        if self.isEnabledFor(VERBOSE):
            self._log(VERBOSE, msg, args, **kwargs)

    setattr(logging.Logger, "verbose", verbose)


_register_verbose_level()


class ContextFilter(logging.Filter):
    """Inject per-request/process context into each log record."""

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
    file_capture_enabled: bool = False,
    file_capture_level: str = "VERBOSE",
    file_capture_directory: str = "logs",
    json_output: bool = True,
    process_name: str | None = None,
    environment: str | None = None,
) -> None:
    """Configure root logging with stdout and optional local file capture.

    This function is idempotent for handler setup: existing root handlers are
    replaced to avoid duplicate emissions when called multiple times.
    """
    _register_verbose_level()
    root = logging.getLogger()
    root.handlers.clear()
    stream_level = _resolve_level(level)
    handlers: list[logging.Handler] = []

    stream_handler = logging.StreamHandler(stream=sys.stdout)
    stream_handler.setLevel(stream_level)
    stream_handler.addFilter(ContextFilter())
    stream_handler.setFormatter(JsonFormatter() if json_output else PlainFormatter())
    handlers.append(stream_handler)

    if file_capture_enabled:
        file_level = _resolve_level(file_capture_level)
        file_handler = _build_file_handler(
            directory=file_capture_directory,
            process_name=process_name,
            json_output=json_output,
        )
        file_handler.setLevel(file_level)
        file_handler.addFilter(ContextFilter())
        handlers.append(file_handler)

    root.setLevel(min(handler.level for handler in handlers))
    for handler in handlers:
        root.addHandler(handler)
    root.propagate = False
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    seed_context: dict[str, str] = {}
    if process_name:
        seed_context[fields.PROCESS_NAME] = process_name
    if environment:
        seed_context[fields.ENVIRONMENT] = environment
    if seed_context:
        from .context import bind_context

        bind_context(**seed_context)


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger using Python's standard logging hierarchy."""
    _register_verbose_level()
    return logging.getLogger(name)


def _resolve_level(level: str) -> int:
    """Resolve one configured logging level name into a numeric value."""
    parsed = logging.getLevelName(level.upper())
    if isinstance(parsed, int):
        return parsed
    raise ValueError(f"unsupported log level: {level}")


def _build_file_handler(
    *,
    directory: str,
    process_name: str | None,
    json_output: bool,
) -> logging.Handler:
    """Build one local file capture handler, creating its directory on demand."""
    log_directory = Path(directory)
    log_directory.mkdir(parents=True, exist_ok=True)
    resolved_process_name = _sanitize_process_name(process_name=process_name)
    handler = logging.FileHandler(
        filename=log_directory / f"{resolved_process_name}.log",
        encoding="utf-8",
    )
    handler.setFormatter(JsonFormatter() if json_output else PlainFormatter())
    return handler


def _sanitize_process_name(*, process_name: str | None) -> str:
    """Return one filesystem-safe process name for local capture filenames."""
    candidate = "" if process_name is None else process_name.strip().lower()
    if candidate == "":
        return "brain"
    sanitized = "".join(
        character
        for character in candidate
        if character.isalnum() or character in {"-", "_"}
    )
    return sanitized or "brain"
