"""Public logging API for shared Brain services.

This package wraps Python's ``logging`` module with opinionated defaults for
stdout emission and structured context propagation.
"""

from .config import configure_logging, get_logger
from .context import bind_context, clear_context, get_context, log_context

__all__ = [
    "bind_context",
    "clear_context",
    "configure_logging",
    "get_context",
    "get_logger",
    "log_context",
]
