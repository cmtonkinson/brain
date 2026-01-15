from agent import _render_signal_message


def test_render_signal_message_transforms_markdown() -> None:
    text = (
        "# Title\n\n"
        "A [link](http://example.com) and ![img](http://img)\n\n"
        "~~gone~~ _ital_ __bold__"
    )
    rendered = _render_signal_message(text)
    assert "**Title**" in rendered
    assert "link (http://example.com)" in rendered
    assert "img (http://img)" in rendered
    assert "~gone~" in rendered
    assert "*ital*" in rendered
    assert "**bold**" in rendered


def test_render_signal_message_handles_code_fence() -> None:
    text = "```python\nx = 1\n```"
    rendered = _render_signal_message(text)
    assert rendered.strip() == "`x = 1`"


def test_render_signal_message_preserves_inline_code() -> None:
    text = "Use `__bold__` and _ital_."
    rendered = _render_signal_message(text)
    assert "`__bold__`" in rendered
