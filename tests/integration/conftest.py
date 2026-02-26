"""Shared fixtures for integration-oriented test modules."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture(scope="function")
def tmp_blob_root(tmp_path: Path) -> Path:
    """Return function-scoped temporary blob root directory."""
    root = tmp_path / "blobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(scope="function")
def clock_freezer(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Freeze random backoff jitter paths by making randomness deterministic."""
    monkeypatch.setattr("resources.adapters.signal.signal_adapter.random", lambda: 0.5)
    yield


@pytest.fixture(scope="session")
def http_stub_server() -> None:
    """Placeholder fixture for local HTTP stub-server contract tests.

    The current adapter suites monkeypatch transport calls directly for determinism.
    This fixture exists as the stable integration harness boundary for future
    migration to a socket-backed in-process server.
    """

    return None
