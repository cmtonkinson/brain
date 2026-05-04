"""Tests for the Console TUI InputHistory buffer."""

from __future__ import annotations

import pytest

from actors.console.widgets.message_input import InputHistory


def test_empty_history_navigation_is_inert() -> None:
    """With nothing recorded, prev and next return None and don't disturb the draft."""
    h = InputHistory(max_size=10)
    assert h.prev("draft") is None
    assert h.next("draft") is None


def test_prev_returns_most_recent_first() -> None:
    """Walking up steps from newest to oldest."""
    h = InputHistory(max_size=10)
    h.record("first")
    h.record("second")
    h.record("third")
    assert h.prev("") == "third"
    assert h.prev("third") == "second"
    assert h.prev("second") == "first"
    assert h.prev("first") is None


def test_next_walks_back_to_draft() -> None:
    """Stepping past the newest entry restores the draft saved on first prev."""
    h = InputHistory(max_size=10)
    h.record("alpha")
    h.record("beta")
    assert h.prev("partial draft") == "beta"
    assert h.prev("beta") == "alpha"
    assert h.next("alpha") == "beta"
    assert h.next("beta") == "partial draft"
    assert h.next("partial draft") is None


def test_draft_preserved_across_arbitrary_navigation() -> None:
    """Draft survives any combination of prev/next while a history entry is shown."""
    h = InputHistory(max_size=10)
    for entry in ("a", "b", "c", "d"):
        h.record(entry)
    assert h.prev("WIP") == "d"
    assert h.prev("d") == "c"
    assert h.prev("c") == "b"
    assert h.next("b") == "c"
    assert h.next("c") == "d"
    assert h.next("d") == "WIP"


def test_record_resets_navigation_state() -> None:
    """Submitting clears the saved draft and returns the index to the tail."""
    h = InputHistory(max_size=10)
    h.record("one")
    assert h.prev("draft-A") == "one"
    h.record("two")
    assert h.next("anything") is None
    assert h.prev("draft-B") == "two"
    assert h.prev("two") == "one"


def test_empty_submission_is_not_recorded_but_resets_state() -> None:
    """Empty record() leaves history alone but still clears navigation/draft."""
    h = InputHistory(max_size=10)
    h.record("kept")
    assert h.prev("draft-A") == "kept"
    h.record("")
    assert h.next("anything") is None
    assert h.prev("draft-B") == "kept"


def test_max_size_evicts_oldest() -> None:
    """A bounded buffer drops the oldest entry once the cap is exceeded."""
    h = InputHistory(max_size=2)
    h.record("a")
    h.record("b")
    h.record("c")
    assert h.prev("") == "c"
    assert h.prev("c") == "b"
    assert h.prev("b") is None


def test_max_size_must_be_positive() -> None:
    """Zero or negative max_size is rejected."""
    with pytest.raises(ValueError):
        InputHistory(max_size=0)
    with pytest.raises(ValueError):
        InputHistory(max_size=-1)
