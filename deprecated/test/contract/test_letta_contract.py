"""Contract tests for Letta HTTP interactions."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from config import settings
from services.letta import LettaService


def _configure_letta(monkeypatch) -> None:
    """Seed Letta settings for contract tests."""
    monkeypatch.setattr(settings.letta, "base_url", "http://letta.test", raising=False)
    monkeypatch.setattr(settings.letta, "api_key", "secret", raising=False)
    monkeypatch.setattr(settings.letta, "agent_name", "brain", raising=False)


def test_search_archival_memory_contract(monkeypatch) -> None:
    """Search archival memory uses the first available endpoint."""
    _configure_letta(monkeypatch)

    with respx.mock(assert_all_called=True) as router:
        router.get("http://letta.test/v1/agents").respond(
            200, json={"agents": [{"id": "agent-1", "name": "brain"}]}
        )
        search_route = router.get(
            "http://letta.test/v1/agents/agent-1/archival-memory/search"
        ).respond(200, json={"results": [{"content": "match"}]})

        service = LettaService()
        response = service.search_archival_memory("hello")

    assert response == "- match"
    assert search_route.called
    assert search_route.calls[0].request.url.params.get("query") == "hello"


def test_insert_to_archival_contract(monkeypatch) -> None:
    """Insert to archival falls back and posts content payload."""
    _configure_letta(monkeypatch)

    with respx.mock(assert_all_called=True) as router:
        router.get("http://letta.test/v1/agents").respond(
            200, json={"agents": [{"id": "agent-1", "name": "brain"}]}
        )
        insert_route = router.post("http://letta.test/v1/agents/agent-1/archival-memory").mock(
            side_effect=[
                httpx.Response(404),
                httpx.Response(200, json={"id": "mem-1"}),
            ]
        )

        service = LettaService()
        response = service.insert_to_archival("remember this")

    assert response == "Saved to memory (id mem-1)."
    assert insert_route.called
    assert json.loads(insert_route.calls[0].request.content.decode("utf-8")) == {
        "text": "remember this"
    }
    assert json.loads(insert_route.calls[1].request.content.decode("utf-8")) == {
        "content": "remember this"
    }


def test_search_archival_memory_raises_when_agent_missing(monkeypatch) -> None:
    """Search archival memory fails fast when the configured agent is missing."""
    _configure_letta(monkeypatch)

    with respx.mock(assert_all_called=True) as router:
        router.get("http://letta.test/v1/agents").respond(
            200, json={"agents": [{"id": "agent-2", "name": "other"}]}
        )

        service = LettaService()
        with pytest.raises(ValueError, match="Letta agent not found"):
            service.search_archival_memory("hello")
