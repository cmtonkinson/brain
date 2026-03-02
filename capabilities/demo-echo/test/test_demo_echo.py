"""Test the demo_echo skill."""

from capabilities.demo_echo.execute import execute


def test_demo_echo():
    """Test that the demo_echo skill returns the correct string."""
    assert execute() == "Hello, World!"
