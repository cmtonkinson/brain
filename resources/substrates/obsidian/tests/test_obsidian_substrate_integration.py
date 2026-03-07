"""Integration-style Obsidian substrate contract tests using transport monkeypatching."""

from __future__ import annotations

from packages.brain_shared.http import HttpStatusError
from resources.substrates.obsidian import (
    ObsidianSubstrateNotFoundError,
    ObsidianSubstrateSettings,
    ObsidianLocalRestSubstrate,
)


class _Resp:
    """Minimal shared-client response fake."""

    def __init__(self, *, status: int, payload: bytes) -> None:
        self.status_code = status
        self.content = payload


def _substrate() -> ObsidianLocalRestSubstrate:
    """Build substrate with deterministic localhost configuration."""
    return ObsidianLocalRestSubstrate(
        settings=ObsidianSubstrateSettings(base_url="http://localhost:27123")
    )


def test_list_directory_http_contract(monkeypatch) -> None:
    """Substrate should parse Local REST API directory payload contract."""
    substrate = _substrate()
    monkeypatch.setattr(
        substrate._client,
        "request",
        lambda *_args, **_kwargs: _Resp(
            status=200, payload=b'{"files":["notes/","todo.md"]}'
        ),
    )
    entries = substrate.list_directory(directory_path="")
    assert len(entries) == 2


def test_not_found_maps_correctly(monkeypatch) -> None:
    """HTTP 404 should map to substrate not-found domain error."""

    def _raise(*_args, **_kwargs):
        raise HttpStatusError(
            message="HTTP 404",
            method="GET",
            url="http://localhost",
            retryable=False,
            status_code=404,
        )

    substrate = _substrate()
    monkeypatch.setattr(substrate._client, "request", _raise)
    try:
        substrate.get_file(file_path="missing.md")
    except ObsidianSubstrateNotFoundError:
        pass
    else:
        raise AssertionError("expected ObsidianSubstrateNotFoundError")
