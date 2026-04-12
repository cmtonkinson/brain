"""Read-only log readers for the dashboard log pane."""

from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

from packages.dashboard.data_sources.base import BasePollingDataSource
from packages.dashboard.models.data_source import RetentionPolicy
from packages.dashboard.models.log_event import DashboardLogEvent


def normalize_log_line(line: str, component: str, source: str) -> DashboardLogEvent:
    """Parse one raw log line into a canonical DashboardLogEvent."""
    line = line.rstrip("\n")
    raw_payload: Any = None
    timestamp: datetime = datetime.now(timezone.utc)
    level = "INFO"
    message = line
    trace_id: str | None = None
    envelope_id: str | None = None

    try:
        data = json.loads(line)
        raw_payload = data
        # extract timestamp
        for ts_key in ("timestamp", "time", "ts", "@timestamp"):
            if ts_key in data:
                val = data[ts_key]
                if isinstance(val, (int, float)):
                    timestamp = datetime.fromtimestamp(val, tz=timezone.utc)
                elif isinstance(val, str):
                    try:
                        timestamp = datetime.fromisoformat(val.replace("Z", "+00:00"))
                    except ValueError:
                        pass
                break
        # extract level
        for lvl_key in ("level", "severity", "lvl"):
            if lvl_key in data:
                level = str(data[lvl_key]).upper()
                break
        # extract message
        for msg_key in ("message", "msg", "text"):
            if msg_key in data:
                message = str(data[msg_key])
                break
        trace_id = data.get("trace_id")
        envelope_id = data.get("envelope_id")
    except (json.JSONDecodeError, ValueError):
        pass  # plain text — use defaults

    return DashboardLogEvent(
        timestamp=timestamp,
        level=level,
        component=component,
        source=source,
        message=message,
        trace_id=trace_id,
        envelope_id=envelope_id,
        raw_payload=raw_payload,
    )


class LogBuffer:
    """Thread-safe bounded ring buffer of DashboardLogEvent."""

    def __init__(self, max_size: int = 5000) -> None:
        self._buf: deque[DashboardLogEvent] = deque(maxlen=max_size)
        self._lock = threading.Lock()

    def append(self, event: DashboardLogEvent) -> None:
        with self._lock:
            self._buf.append(event)

    def get_recent(self, n: int) -> list[DashboardLogEvent]:
        with self._lock:
            items = list(self._buf)
        return items[-n:] if n < len(items) else items

    def get_all(self) -> list[DashboardLogEvent]:
        with self._lock:
            return list(self._buf)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)


class FileLogSource:
    """Read-only file log reader with backfill and follow."""

    def __init__(
        self, path: str, component: str, buffer: LogBuffer, backfill_lines: int = 200
    ) -> None:
        self._path = path
        self._component = component
        self._buffer = buffer
        self._backfill_lines = backfill_lines
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _backfill(self) -> None:
        """Read last N lines from file into buffer. Public for testing."""
        try:
            with open(self._path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
                for line in lines[-self._backfill_lines :]:
                    if line.strip():
                        self._buffer.append(
                            normalize_log_line(line, self._component, "file")
                        )
        except OSError:
            pass

    def _follow(self) -> None:
        """Follow file for new lines until stop_event is set."""
        fh = None
        try:
            fh = open(self._path, "r", encoding="utf-8", errors="replace")
            fh.seek(0, 2)  # seek to end
            while not self._stop_event.is_set():
                line = fh.readline()
                if line:
                    if line.strip():
                        self._buffer.append(
                            normalize_log_line(line, self._component, "file")
                        )
                else:
                    self._stop_event.wait(0.5)
                    # attempt reopen if file handle is stale
                    try:
                        fh.seek(fh.tell())
                    except OSError:
                        fh.close()
                        try:
                            fh = open(
                                self._path, "r", encoding="utf-8", errors="replace"
                            )
                            fh.seek(0, 2)
                        except OSError:
                            self._stop_event.wait(1.0)
        except OSError:
            pass
        finally:
            if fh is not None:
                try:
                    fh.close()
                except OSError:
                    pass

    def start(self) -> None:
        self._backfill()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._follow, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None


class DockerLogSource:
    """Read container logs via Docker SDK with backfill and follow."""

    def __init__(
        self,
        container_name: str,
        component: str,
        buffer: LogBuffer,
        backfill_lines: int = 200,
    ) -> None:
        self._container_name = container_name
        self._component = component
        self._buffer = buffer
        self._backfill_lines = backfill_lines
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        try:
            import docker  # noqa: PLC0415

            client = docker.from_env()
            container = client.containers.get(self._container_name)
            # backfill
            logs = container.logs(tail=self._backfill_lines, stream=False)
            for line in logs.decode("utf-8", errors="replace").splitlines():
                if line.strip():
                    self._buffer.append(
                        normalize_log_line(line, self._component, "docker")
                    )
            # follow
            for chunk in container.logs(stream=True, follow=True):
                if self._stop_event.is_set():
                    break
                line = chunk.decode("utf-8", errors="replace").rstrip("\n")
                if line.strip():
                    self._buffer.append(
                        normalize_log_line(line, self._component, "docker")
                    )
        except Exception:
            pass  # never crash; docker unavailable or container missing

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None


class LogDataSource(BasePollingDataSource[list[DashboardLogEvent]]):
    """Wraps LogBuffer into the DataSource protocol."""

    def __init__(self, buffer: LogBuffer, poll_interval: float = 0.5) -> None:
        super().__init__(poll_interval, RetentionPolicy(family="event", max_items=5000))
        self._log_buffer = buffer

    def _fetch(self) -> list[DashboardLogEvent]:
        return self._log_buffer.get_all()
