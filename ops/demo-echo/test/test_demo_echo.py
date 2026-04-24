"""Test the demo-echo op."""

import importlib.util
from pathlib import Path


def _load_execute():
    spec = importlib.util.spec_from_file_location(
        "demo_echo_execute", Path(__file__).resolve().parent.parent / "execute.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.execute


def test_demo_echo() -> None:
    """Test that the demo-echo op returns the correct string."""
    assert _load_execute()() == "Hello, World!"
