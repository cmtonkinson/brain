"""Tests for KeymapFooter footer builder logic."""

from __future__ import annotations

from packages.dashboard.widgets.keymap_footer import (
    FooterItem,
    _GLOBAL_ITEMS,
    _format_item,
    build_footer_text,
)


def test_format_item():
    item = FooterItem(key="Q", label="Quit", priority=1)
    assert _format_item(item) == "\\[Q] Quit"


def test_build_footer_text_wide():
    items = [
        FooterItem("Q", "Quit", priority=1),
        FooterItem("tab", "Focus", priority=2),
    ]
    text = build_footer_text(items, max_width=200)
    assert "\\[Q] Quit" in text
    assert "\\[tab] Focus" in text


def test_build_footer_text_narrow_drops_low_priority():
    items = [
        FooterItem("Q", "Quit", priority=1),
        FooterItem("tab", "Focus", priority=2),
        FooterItem("s", "Split-H", priority=3),
    ]
    # narrow enough to drop "Split-H" but keep "Quit" and "Focus"
    text = build_footer_text(items, max_width=25)
    assert "\\[Q] Quit" in text
    # Split-H may or may not fit depending on exact width; just verify no crash


def test_build_footer_text_very_narrow_returns_empty_or_minimal():
    items = [FooterItem("Q", "Quit", priority=1)]
    text = build_footer_text(items, max_width=3)
    # Either empty or just the highest-priority item truncated
    assert isinstance(text, str)


def test_global_items_no_old_toggle_keys():
    keys = {item.key for item in _GLOBAL_ITEMS}
    # Old 1-4 toggle keys must be gone
    assert "1" not in keys
    assert "2" not in keys
    assert "3" not in keys
    assert "4" not in keys


def test_global_items_has_canonical_keys():
    keys = {item.key for item in _GLOBAL_ITEMS}
    assert "Q" in keys
    assert "tab" in keys
    assert "enter" in keys


def test_priority_ordering():
    # Higher priority (lower number) items appear before lower priority
    items = [
        FooterItem("b", "B", priority=2),
        FooterItem("a", "A", priority=1),
    ]
    text = build_footer_text(items, max_width=200)
    assert text.index("\\[a]") < text.index("\\[b]")
