"""Integration-style Obsidian substrate contract tests using transport monkeypatching."""

from __future__ import annotations

from urllib import error as urllib_error

import resources.substrates.obsidian.obsidian_substrate as substrate_module
from resources.substrates.obsidian import (
    ObsidianSubstrateNotFoundError,
    ObsidianSubstrateSettings,
    ObsidianLocalRestSubstrate,
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


def _substrate() -> ObsidianLocalRestSubstrate:
    """Build substrate with deterministic localhost configuration."""
    return ObsidianLocalRestSubstrate(
        settings=ObsidianSubstrateSettings(base_url="http://localhost:27123")
    )


def test_list_directory_http_contract(monkeypatch) -> None:
    """Substrate should parse Local REST API directory payload contract."""
    monkeypatch.setattr(
        substrate_module.urllib_request,
        "urlopen",
        lambda *_args, **_kwargs: _Resp(
            status=200, payload=b'{"files":["notes/","todo.md"]}'
        ),
    )
    entries = _substrate().list_directory(directory_path="")
    assert len(entries) == 2


def test_not_found_maps_correctly(monkeypatch) -> None:
    """HTTP 404 should map to substrate not-found domain error."""

    def _raise(*_args, **_kwargs):
        raise urllib_error.HTTPError("u", 404, "nf", None, None)

    monkeypatch.setattr(substrate_module.urllib_request, "urlopen", _raise)
    try:
        _substrate().get_file(file_path="missing.md")
    except ObsidianSubstrateNotFoundError:
        pass
    else:
        raise AssertionError("expected ObsidianSubstrateNotFoundError")
