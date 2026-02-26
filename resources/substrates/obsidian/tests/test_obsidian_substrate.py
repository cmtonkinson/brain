"""Unit tests for Obsidian Local REST substrate HTTP/error semantics."""

from __future__ import annotations

from urllib import error as urllib_error

import pytest

import resources.substrates.obsidian.obsidian_substrate as substrate_module
from resources.substrates.obsidian import (
    ObsidianSubstrateAlreadyExistsError,
    ObsidianSubstrateConflictError,
    ObsidianSubstrateDependencyError,
    ObsidianSubstrateNotFoundError,
    ObsidianSubstrateSettings,
    ObsidianFileRecord,
    ObsidianLocalRestSubstrate,
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


def _substrate() -> ObsidianLocalRestSubstrate:
    """Build substrate with deterministic localhost configuration."""
    return ObsidianLocalRestSubstrate(
        settings=ObsidianSubstrateSettings(base_url="http://localhost:27123")
    )


def test_list_directory_maps_payload(monkeypatch: object) -> None:
    """Directory list should map API ``files`` entries into typed DTOs."""
    monkeypatch.setattr(
        substrate_module.urllib_request,
        "urlopen",
        lambda *_args, **_kwargs: _FakeResponse(
            status=200,
            payload=(b'{"files":["notes/","todo.md"]}'),
        ),
    )
    substrate = _substrate()

    entries = substrate.list_directory(directory_path="")

    assert len(entries) == 2
    assert entries[0].path == "notes"
    assert entries[0].entry_type.value == "directory"
    assert entries[1].path == "todo.md"
    assert entries[1].entry_type.value == "file"


def test_status_404_maps_to_not_found(monkeypatch: object) -> None:
    """HTTP 404 should map to substrate not-found error type."""
    monkeypatch.setattr(
        substrate_module.urllib_request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_FakeHttpError(404)),
    )
    substrate = _substrate()

    with pytest.raises(ObsidianSubstrateNotFoundError):
        substrate.get_file(file_path="missing.md")


def test_status_409_maps_to_already_exists(monkeypatch: object) -> None:
    """HTTP 409 should map to substrate already-exists error type."""
    monkeypatch.setattr(
        substrate_module.urllib_request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_FakeHttpError(409)),
    )
    substrate = _substrate()

    with pytest.raises(ObsidianSubstrateAlreadyExistsError):
        substrate.create_file(file_path="note.md", content="x")


def test_status_412_maps_to_conflict(monkeypatch: object) -> None:
    """HTTP 412 should map to optimistic-concurrency conflict type."""
    monkeypatch.setattr(
        substrate_module.urllib_request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_FakeHttpError(412)),
    )
    substrate = _substrate()

    with pytest.raises(ObsidianSubstrateConflictError):
        substrate.update_file(
            file_path="note.md", content="x", if_revision="r1", force=False
        )


def test_retry_exhaustion_raises_dependency_error(monkeypatch: object) -> None:
    """Repeated network failures should raise dependency failure after retries."""
    monkeypatch.setattr(
        substrate_module.urllib_request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            urllib_error.URLError("connection refused")
        ),
    )
    substrate = ObsidianLocalRestSubstrate(
        settings=ObsidianSubstrateSettings(
            base_url="http://localhost:27123",
            max_retries=1,
        )
    )

    with pytest.raises(ObsidianSubstrateDependencyError):
        substrate.search_files(query="brain", directory_scope="", limit=5)


def test_append_file_does_not_retry_on_dependency_failure(monkeypatch: object) -> None:
    """Append should not retry because POST append is non-idempotent."""
    calls = {"count": 0}

    def _urlopen(*_args: object, **_kwargs: object) -> object:
        calls["count"] += 1
        raise urllib_error.URLError("connection refused")

    monkeypatch.setattr(substrate_module.urllib_request, "urlopen", _urlopen)
    substrate = ObsidianLocalRestSubstrate(
        settings=ObsidianSubstrateSettings(
            base_url="http://localhost:27123",
            max_retries=3,
        )
    )

    with pytest.raises(ObsidianSubstrateDependencyError):
        substrate.append_file(
            file_path="notes/todo.md",
            content="more",
            if_revision="",
            force=False,
        )

    assert calls["count"] == 1


def test_create_directory_uses_sentinel_file_lifecycle(monkeypatch: object) -> None:
    """Create directory should write and then remove a temporary sentinel file."""
    substrate = _substrate()
    calls: list[str] = []

    def _list_directory(*, directory_path: str) -> list[object]:
        if directory_path == "notes/new":
            raise ObsidianSubstrateNotFoundError("missing")
        return []

    def _request_raw(**kwargs: object) -> _FakeResponse:
        calls.append(f"{kwargs['method']}:{kwargs['endpoint']}")
        return _FakeResponse(status=200, payload=b"{}")

    def _delete_file(*, file_path: str, missing_ok: bool) -> bool:
        calls.append(f"DELETE_FILE:{file_path}:{missing_ok}")
        return True

    monkeypatch.setattr(substrate, "list_directory", _list_directory)
    monkeypatch.setattr(substrate, "_request_raw", _request_raw)
    monkeypatch.setattr(substrate, "_delete_file", _delete_file)

    entry = substrate.create_directory(directory_path="notes/new", recursive=False)

    assert entry.path == "notes/new"
    assert entry.entry_type.value == "directory"
    assert calls[0].startswith("PUT:/vault/notes/new/.brain_directory_")
    assert calls[1].startswith("DELETE_FILE:notes/new/.brain_directory_")
    assert calls[1].endswith(".md:True")


def test_health_reports_ready_when_list_directory_succeeds(monkeypatch: object) -> None:
    """Health should report ready when shallow vault list succeeds."""
    substrate = _substrate()
    monkeypatch.setattr(substrate, "list_directory", lambda **_: [])

    result = substrate.health()

    assert result.ready is True
    assert result.detail == "ok"


def test_health_reports_not_ready_when_list_directory_fails(
    monkeypatch: object,
) -> None:
    """Health should degrade when shallow vault list raises dependency error."""
    substrate = _substrate()

    def _raise(**_: object) -> list[object]:
        raise ObsidianSubstrateDependencyError("connection refused")

    monkeypatch.setattr(substrate, "list_directory", _raise)

    result = substrate.health()

    assert result.ready is False
    assert "connection refused" in result.detail


def test_delete_directory_empty_returns_success(monkeypatch: object) -> None:
    """Delete directory should succeed for existing empty directories."""
    substrate = _substrate()
    calls: list[str] = []
    monkeypatch.setattr(substrate, "list_directory", lambda **_: [])
    monkeypatch.setattr(
        substrate,
        "_request_raw",
        lambda **kwargs: (
            calls.append(f"{kwargs['method']}:{kwargs['endpoint']}"),
            _FakeResponse(status=200, payload=b"{}"),
        )[1],
    )

    deleted = substrate.delete_directory(
        directory_path="notes/empty",
        recursive=False,
        missing_ok=False,
        use_trash=True,
    )

    assert deleted is True
    assert calls == ["DELETE:/vault/notes/empty/"]


def test_move_path_raises_conflict_when_target_file_exists(monkeypatch: object) -> None:
    """File moves should fail when target path already exists."""
    substrate = _substrate()

    def _get_file(*, file_path: str) -> ObsidianFileRecord:
        if file_path == "notes/source.md":
            return ObsidianFileRecord(path=file_path, content="x", revision="r1")
        if file_path == "notes/target.md":
            return ObsidianFileRecord(path=file_path, content="y", revision="r2")
        raise ObsidianSubstrateNotFoundError("missing")

    monkeypatch.setattr(substrate, "get_file", _get_file)

    with pytest.raises(ObsidianSubstrateAlreadyExistsError):
        substrate.move_path(
            source_path="notes/source.md",
            target_path="notes/target.md",
            if_revision="",
            force=False,
        )
