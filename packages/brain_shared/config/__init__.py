"""Public API for shared Brain configuration utilities."""

from .defaults import BUILTIN_DEFAULTS
from .loader import DEFAULT_CONFIG_PATH, load_config

__all__ = [
    "BUILTIN_DEFAULTS",
    "DEFAULT_CONFIG_PATH",
    "load_config",
]
