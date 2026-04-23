"""Tests for BasePollingDataSource — synchronous _poll_once() only, no threading."""

from __future__ import annotations

from lib.dashboard.data_sources.base import BasePollingDataSource
from lib.dashboard.models.data_source import RetentionPolicy


class _ConstantSource(BasePollingDataSource[int]):
    def __init__(self) -> None:
        super().__init__(1.0, RetentionPolicy(family="event", max_items=10))

    def _fetch(self) -> int:
        return 42


class _FailingSource(BasePollingDataSource[int]):
    def __init__(self) -> None:
        super().__init__(1.0, RetentionPolicy(family="event", max_items=10))

    def _fetch(self) -> int:
        raise RuntimeError("boom")


def test_poll_once_updates_current() -> None:
    s = _ConstantSource()
    s._poll_once()
    assert s.get_current() == 42


def test_poll_once_sets_snapshot() -> None:
    s = _ConstantSource()
    s._poll_once()
    snap = s.get_snapshot()
    assert snap.data == 42
    assert snap.stale is False
    assert snap.error is None


def test_failing_fetch_sets_stale_and_error() -> None:
    s = _FailingSource()
    s._poll_once()
    snap = s.get_snapshot()
    assert snap.stale is True
    assert snap.error is not None
    assert "boom" in snap.error


def test_last_good_data_preserved_after_failure() -> None:
    class _OnceGoodThenFail(BasePollingDataSource[int]):
        def __init__(self) -> None:
            super().__init__(1.0, RetentionPolicy(family="event", max_items=10))
            self._calls = 0

        def _fetch(self) -> int:
            self._calls += 1
            if self._calls == 1:
                return 99
            raise RuntimeError("fail")

    s = _OnceGoodThenFail()
    s._poll_once()
    s._poll_once()
    assert s.get_snapshot().data == 99


def test_is_stale_when_never_refreshed() -> None:
    s = _ConstantSource()
    assert s.is_stale() is True


def test_get_history_insertion_order() -> None:
    class _CountSource(BasePollingDataSource[int]):
        def __init__(self) -> None:
            super().__init__(1.0, RetentionPolicy(family="event", max_items=10))
            self._n = 0

        def _fetch(self) -> int:
            self._n += 1
            return self._n

    s = _CountSource()
    s._poll_once()
    s._poll_once()
    s._poll_once()
    assert list(s.get_history().records) == [1, 2, 3]
