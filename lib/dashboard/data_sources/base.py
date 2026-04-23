"""Abstract base classes for dashboard data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime, timezone
import threading
from typing import Generic, TypeVar

from lib.dashboard.models.data_source import (
    History,
    RetentionPolicy,
    Snapshot,
    TemporalCursor,
    Viewport,
)

T = TypeVar("T")


class DataSource(ABC, Generic[T]):
    """Protocol all concrete data sources must implement."""

    @abstractmethod
    def get_current(self) -> T | None: ...

    @abstractmethod
    def get_snapshot(self) -> Snapshot[T]: ...

    @abstractmethod
    def get_history(self) -> History[T]: ...

    @abstractmethod
    def get_viewport(self, cursor: TemporalCursor | None = None) -> Viewport[T]: ...

    @abstractmethod
    def is_stale(self) -> bool: ...

    @abstractmethod
    def last_refreshed_at(self) -> datetime | None: ...

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...


class BasePollingDataSource(DataSource[T]):
    """Concrete base that implements start/stop/polling loop via threading.Thread."""

    def __init__(
        self, poll_interval_seconds: float, retention: RetentionPolicy
    ) -> None:
        self._poll_interval = poll_interval_seconds
        self._retention = retention
        self._current: T | None = None
        self._snapshot: Snapshot[T] = Snapshot(data=None, stale=False)
        maxlen = retention.max_items if retention.max_items is not None else 500
        self._history: deque[T] = deque(maxlen=maxlen)
        self._last_refreshed_at: datetime | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @abstractmethod
    def _fetch(self) -> T | None: ...

    def _normalize(self, raw: T) -> T:
        return raw

    def _poll_once(self) -> None:
        try:
            raw = self._fetch()
            value = self._normalize(raw) if raw is not None else None
            with self._lock:
                self._current = value
                self._snapshot = Snapshot(
                    data=value,
                    stale=False,
                    error=None,
                    refreshed_at=datetime.now(timezone.utc),
                )
                if value is not None:
                    self._history.append(value)
                self._last_refreshed_at = datetime.now(timezone.utc)
        except Exception as e:
            with self._lock:
                self._snapshot = Snapshot(
                    data=self._current,
                    stale=True,
                    error=str(e),
                    refreshed_at=self._snapshot.refreshed_at,
                )

    def _polling_loop(self) -> None:
        while not self._stop_event.is_set():
            self._poll_once()
            self._stop_event.wait(self._poll_interval)

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._polling_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        close = getattr(self, "close", None)
        if callable(close):
            close()

    def is_stale(self) -> bool:
        with self._lock:
            last = self._last_refreshed_at
        if last is None:
            return True
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        return elapsed > 3 * self._poll_interval

    def get_current(self) -> T | None:
        with self._lock:
            return self._current

    def get_snapshot(self) -> Snapshot[T]:
        with self._lock:
            return self._snapshot

    def get_history(self) -> History[T]:
        with self._lock:
            return History(
                records=tuple(self._history),
                retention=self._retention,
                live_edge_at=self._last_refreshed_at,
            )

    def get_viewport(self, cursor: TemporalCursor | None = None) -> Viewport[T]:
        with self._lock:
            return Viewport(
                data=self._current,
                mode="follow",
                at_live_edge=True,
                live_edge_at=self._last_refreshed_at,
            )

    def last_refreshed_at(self) -> datetime | None:
        with self._lock:
            return self._last_refreshed_at
