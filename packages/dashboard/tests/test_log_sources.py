from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


from packages.dashboard.data_sources.logs import (
    DockerLogSource,
    FileLogSource,
    LogBuffer,
    normalize_log_line,
)
from packages.dashboard.models.log_event import DashboardLogEvent


def test_normalize_json_line():
    line = json.dumps(
        {
            "timestamp": "2024-01-01T00:00:00+00:00",
            "level": "warning",
            "message": "hello",
            "trace_id": "abc",
        }
    )
    evt = normalize_log_line(line, "core", "file")
    assert evt.level == "WARNING"
    assert evt.message == "hello"
    assert evt.trace_id == "abc"
    assert evt.component == "core"
    assert evt.source == "file"


def test_normalize_plain_text():
    evt = normalize_log_line("plain text line", "agent", "docker")
    assert evt.level == "INFO"
    assert evt.message == "plain text line"
    assert evt.component == "agent"
    assert evt.raw_payload is None


def test_log_buffer_append_and_get_recent():
    buf = LogBuffer(max_size=10)
    for i in range(5):
        buf.append(
            DashboardLogEvent(
                timestamp=datetime.now(timezone.utc),
                level="INFO",
                component="c",
                source="file",
                message=f"msg{i}",
            )
        )
    recent = buf.get_recent(3)
    assert len(recent) == 3
    assert recent[-1].message == "msg4"


def test_log_buffer_eviction():
    buf = LogBuffer(max_size=3)
    for i in range(4):
        buf.append(
            DashboardLogEvent(
                timestamp=datetime.now(timezone.utc),
                level="INFO",
                component="c",
                source="file",
                message=f"msg{i}",
            )
        )
    assert len(buf) == 3


def test_file_log_source_backfill(tmp_path: Path):
    log_file = tmp_path / "test.log"
    log_file.write_text("line1\nline2\nline3\n")
    buf = LogBuffer()
    src = FileLogSource(path=str(log_file), component="core", buffer=buf)
    src._backfill()
    assert len(buf) == 3


def test_docker_log_source_handles_error():
    buf = LogBuffer()
    src = DockerLogSource(container_name="brain-core", component="core", buffer=buf)
    import sys
    import types

    fake_docker = types.ModuleType("docker")
    fake_docker.from_env = lambda: (_ for _ in ()).throw(
        Exception("docker not available")
    )  # type: ignore[attr-defined]
    with patch.dict(sys.modules, {"docker": fake_docker}):
        src.start()
        src.stop()
    # no crash, buffer may be empty
    assert True
