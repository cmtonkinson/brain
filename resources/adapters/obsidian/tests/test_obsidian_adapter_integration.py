"""Integration-style Obsidian adapter contract tests using transport monkeypatching."""

from __future__ import annotations

from urllib import error as urllib_error

import resources.adapters.obsidian.obsidian_adapter as adapter_module
from resources.adapters.obsidian import (
    ObsidianAdapterNotFoundError,
    ObsidianAdapterSettings,
    ObsidianLocalRestAdapter,
)


class _Resp:
    """Minimal context-managed HTTP response fake."""

    def __init__(self, *, status: int, payload: bytes) -> None:
        self.status = status
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def _adapter() -> ObsidianLocalRestAdapter:
    """Build adapter with deterministic localhost configuration."""
    return ObsidianLocalRestAdapter(
        settings=ObsidianAdapterSettings(base_url="http://localhost:27124")
    )


def test_list_directory_http_contract(monkeypatch) -> None:
    """Adapter should parse Local REST API directory payload contract."""
    monkeypatch.setattr(
        adapter_module.urllib_request,
        "urlopen",
        lambda *_args, **_kwargs: _Resp(
            status=200, payload=b'{"files":["notes/","todo.md"]}'
        ),
    )
    entries = _adapter().list_directory(directory_path="")
    assert len(entries) == 2


def test_not_found_maps_correctly(monkeypatch) -> None:
    """HTTP 404 should map to adapter not-found domain error."""

    def _raise(*_args, **_kwargs):
        raise urllib_error.HTTPError("u", 404, "nf", None, None)

    monkeypatch.setattr(adapter_module.urllib_request, "urlopen", _raise)
    try:
        _adapter().get_file(file_path="missing.md")
    except ObsidianAdapterNotFoundError:
        pass
    else:
        raise AssertionError("expected ObsidianAdapterNotFoundError")
