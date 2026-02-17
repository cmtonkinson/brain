"""Unit tests for prompt rendering."""

import pytest

from prompts import render_prompt


def test_render_prompt_replaces_placeholders() -> None:
    """Placeholder values are interpolated into prompts."""
    rendered = render_prompt("system/assistant", {"user": "Chris"})
    assert "Chris" in rendered


def test_render_prompt_missing_placeholder_raises() -> None:
    """Missing placeholders raise a ValueError."""
    with pytest.raises(ValueError):
        render_prompt("system/assistant", {"missing": "value"})
