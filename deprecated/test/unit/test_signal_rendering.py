"""Unit tests for Signal markdown rendering."""

import pytest

from agent import _render_signal_message


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        (
            (
                "# Title\n\n"
                "A [link](http://example.com) and ![img](http://img)\n\n"
                "~~gone~~ _ital_ __bold__"
            ),
            (
                "**Title**\n\n"
                "A link (http://example.com) and img (http://img)\n\n"
                "~gone~ *ital* **bold**"
            ),
        ),
        (
            ("## Notes\n" "- Alpha\n" "- Beta\n" "\n" "> quoted line\n" "Normal text"),
            ("**Notes**\n" "- Alpha\n" "- Beta\n" "\n" "> quoted line\n" "Normal text"),
        ),
        (
            "```python\nx = 1\n```",
            "`x = 1`",
        ),
        (
            "Use `__bold__` and _ital_.",
            "Use `__bold__` and *ital*.",
        ),
    ],
)
def test_render_signal_message_golden_cases(markdown: str, expected: str) -> None:
    """Golden tests for heading, list, link, and code formatting."""
    rendered = _render_signal_message(markdown)
    assert rendered == expected
