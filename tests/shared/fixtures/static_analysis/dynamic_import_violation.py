"""Negative fixture: dynamic imports that must be banned."""

import importlib
from importlib import import_module


def bad_dynamic_import() -> object:
    """Resolve a module dynamically."""
    mod = importlib.import_module("math")
    other = import_module("json")
    builtin = __import__("os")
    return mod, other, builtin
