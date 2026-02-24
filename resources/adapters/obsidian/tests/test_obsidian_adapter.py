"""Unit tests for Obsidian Local REST adapter HTTP/error semantics."""

from __future__ import annotations

from urllib import error as urllib_error

import pytest

import resources.adapters.obsidian.obsidian_adapter as adapter_module
from resources.adapters.obsidian import (
    ObsidianAdapterAlreadyExistsError,
    ObsidianAdapterConflictError,
    ObsidianAdapterDependencyError,
    ObsidianAdapterNotFoundError,
    ObsidianFileRecord,
    ObsidianAdapterSettings,
    ObsidianLocalRestAdapter,
)


class _FakeResponse:
    """Minimal HTTP response fake implementing context-manager methods."""

    def __init__(self, *, status: int, payload: bytes) -> None:
        self.status = status
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _FakeHttpError(urllib_error.HTTPError):
    """HTTPError subclass with deterministic body for mapping tests."""

    def __init__(self, code: int, body: bytes = b"") -> None:
        super().__init__(
            url="http://localhost",
            code=code,
            msg="error",
            hdrs=None,
            fp=None,
        )
        self._body = body

    def read(self, *_: object, **__: object) -> bytes:
        return self._body


def _adapter() -> ObsidianLocalRestAdapter:
    """Build adapter with deterministic localhost configuration."""
    return ObsidianLocalRestAdapter(
        settings=ObsidianAdapterSettings(base_url="http://localhost:27124")
    )


def test_list_directory_maps_payload(monkeypatch: object) -> None:
    """Directory list should map API ``files`` entries into typed DTOs."""
    monkeypatch.setattr(
        adapter_module.urllib_request,
        "urlopen",
        lambda *_args, **_kwargs: _FakeResponse(
            status=200,
            payload=(b'{"files":["notes/","todo.md"]}'),
        ),
    )
    adapter = _adapter()

    entries = adapter.list_directory(directory_path="")

    assert len(entries) == 2
    assert entries[0].path == "notes"
    assert entries[0].entry_type.value == "directory"
    assert entries[1].path == "todo.md"
    assert entries[1].entry_type.value == "file"


def test_status_404_maps_to_not_found(monkeypatch: object) -> None:
    """HTTP 404 should map to adapter not-found error type."""
    monkeypatch.setattr(
        adapter_module.urllib_request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_FakeHttpError(404)),
    )
    adapter = _adapter()

    with pytest.raises(ObsidianAdapterNotFoundError):
        adapter.get_file(file_path="missing.md")


def test_status_409_maps_to_already_exists(monkeypatch: object) -> None:
    """HTTP 409 should map to adapter already-exists error type."""
    monkeypatch.setattr(
        adapter_module.urllib_request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_FakeHttpError(409)),
    )
    adapter = _adapter()

    with pytest.raises(ObsidianAdapterAlreadyExistsError):
        adapter.create_file(file_path="note.md", content="x")


def test_status_412_maps_to_conflict(monkeypatch: object) -> None:
    """HTTP 412 should map to optimistic-concurrency conflict type."""
    monkeypatch.setattr(
        adapter_module.urllib_request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_FakeHttpError(412)),
    )
    adapter = _adapter()

    with pytest.raises(ObsidianAdapterConflictError):
        adapter.update_file(
            file_path="note.md", content="x", if_revision="r1", force=False
        )


def test_retry_exhaustion_raises_dependency_error(monkeypatch: object) -> None:
    """Repeated network failures should raise dependency failure after retries."""
    monkeypatch.setattr(
        adapter_module.urllib_request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            urllib_error.URLError("connection refused")
        ),
    )
    adapter = ObsidianLocalRestAdapter(
        settings=ObsidianAdapterSettings(
            base_url="http://localhost:27124",
            max_retries=1,
        )
    )

    with pytest.raises(ObsidianAdapterDependencyError):
        adapter.search_files(query="brain", directory_scope="", limit=5)


def test_append_file_does_not_retry_on_dependency_failure(monkeypatch: object) -> None:
    """Append should not retry because POST append is non-idempotent."""
    calls = {"count": 0}

    def _urlopen(*_args: object, **_kwargs: object) -> object:
        calls["count"] += 1
        raise urllib_error.URLError("connection refused")

    monkeypatch.setattr(adapter_module.urllib_request, "urlopen", _urlopen)
    adapter = ObsidianLocalRestAdapter(
        settings=ObsidianAdapterSettings(
            base_url="http://localhost:27124",
            max_retries=3,
        )
    )

    with pytest.raises(ObsidianAdapterDependencyError):
        adapter.append_file(
            file_path="notes/todo.md",
            content="more",
            if_revision="",
            force=False,
        )

    assert calls["count"] == 1


def test_create_directory_uses_sentinel_file_lifecycle(monkeypatch: object) -> None:
    """Create directory should write and then remove a temporary sentinel file."""
    adapter = _adapter()
    calls: list[str] = []

    def _list_directory(*, directory_path: str) -> list[object]:
        if directory_path == "notes/new":
            raise ObsidianAdapterNotFoundError("missing")
        return []

    def _request_raw(**kwargs: object) -> _FakeResponse:
        calls.append(f"{kwargs['method']}:{kwargs['endpoint']}")
        return _FakeResponse(status=200, payload=b"{}")

    def _delete_file(*, file_path: str, missing_ok: bool) -> bool:
        calls.append(f"DELETE_FILE:{file_path}:{missing_ok}")
        return True

    monkeypatch.setattr(adapter, "list_directory", _list_directory)
    monkeypatch.setattr(adapter, "_request_raw", _request_raw)
    monkeypatch.setattr(adapter, "_delete_file", _delete_file)

    entry = adapter.create_directory(directory_path="notes/new", recursive=False)

    assert entry.path == "notes/new"
    assert entry.entry_type.value == "directory"
    assert calls[0].startswith("PUT:/vault/notes/new/.brain_directory_")
    assert calls[1].startswith("DELETE_FILE:notes/new/.brain_directory_")
    assert calls[1].endswith(".md:True")


def test_delete_directory_empty_returns_success(monkeypatch: object) -> None:
    """Delete directory should succeed for existing empty directories."""
    adapter = _adapter()
    calls: list[str] = []
    monkeypatch.setattr(adapter, "list_directory", lambda **_: [])
    monkeypatch.setattr(
        adapter,
        "_request_raw",
        lambda **kwargs: (
            calls.append(f"{kwargs['method']}:{kwargs['endpoint']}"),
            _FakeResponse(status=200, payload=b"{}"),
        )[1],
    )

    deleted = adapter.delete_directory(
        directory_path="notes/empty",
        recursive=False,
        missing_ok=False,
        use_trash=True,
    )

    assert deleted is True
    assert calls == ["DELETE:/vault/notes/empty/"]


def test_move_path_raises_conflict_when_target_file_exists(monkeypatch: object) -> None:
    """File moves should fail when target path already exists."""
    adapter = _adapter()

    def _get_file(*, file_path: str) -> ObsidianFileRecord:
        if file_path == "notes/source.md":
            return ObsidianFileRecord(path=file_path, content="x", revision="r1")
        if file_path == "notes/target.md":
            return ObsidianFileRecord(path=file_path, content="y", revision="r2")
        raise ObsidianAdapterNotFoundError("missing")

    monkeypatch.setattr(adapter, "get_file", _get_file)

    with pytest.raises(ObsidianAdapterAlreadyExistsError):
        adapter.move_path(
            source_path="notes/source.md",
            target_path="notes/target.md",
            if_revision="",
            force=False,
        )
