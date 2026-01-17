"""Unit tests for Letta service parsing and fallbacks."""

from __future__ import annotations

import httpx
import pytest

from services.letta import LettaService


def _build_response(
    status_code: int,
    *,
    json_data: object | None = None,
    content: str | bytes | None = None,
    method: str = "GET",
    url: str = "http://letta.test",
) -> httpx.Response:
    """Create a synthetic httpx response with a bound request."""
    request = httpx.Request(method, url)
    return httpx.Response(status_code=status_code, json=json_data, content=content, request=request)


def test_extract_response_text_prefers_text_fields() -> None:
    """Extract response text from simple dictionary payloads."""
    service = LettaService()
    payload = {"message": "hello"}

    assert service._extract_response_text(payload) == "hello"


def test_extract_response_text_reads_assistant_list() -> None:
    """Extract response text from assistant messages in list payloads."""
    service = LettaService()
    payload = [
        {"role": "user", "content": "ignore"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ],
        },
    ]

    assert service._extract_response_text(payload) == "first\nsecond"


def test_extract_response_text_raises_on_missing_content() -> None:
    """Extract response text raises when no assistant content exists."""
    service = LettaService()
    payload = {"unexpected": "shape"}

    with pytest.raises(ValueError, match="did not include assistant content"):
        service._extract_response_text(payload)


def test_post_with_fallbacks_skips_unavailable(monkeypatch) -> None:
    """POST fallback continues after 404/422 and returns first valid JSON."""
    service = LettaService()
    responses = [
        _build_response(404, content="missing", method="POST"),
        _build_response(200, json_data={"ok": True}, method="POST"),
    ]

    def _fake_post(*args, **kwargs) -> httpx.Response:
        return responses.pop(0)

    monkeypatch.setattr(httpx, "post", _fake_post)

    data = service._post_with_fallbacks([("http://letta.test/a", {}), ("http://letta.test/b", {})])

    assert data == {"ok": True}


def test_post_with_fallbacks_raises_after_exhaustion(monkeypatch) -> None:
    """POST fallback raises a RuntimeError after all endpoints fail."""
    service = LettaService()
    responses = [
        _build_response(404, content="missing", method="POST"),
        _build_response(422, content="invalid", method="POST"),
    ]

    def _fake_post(*args, **kwargs) -> httpx.Response:
        return responses.pop(0)

    monkeypatch.setattr(httpx, "post", _fake_post)

    with pytest.raises(RuntimeError, match="last status=422"):
        service._post_with_fallbacks([("http://letta.test/a", {}), ("http://letta.test/b", {})])


def test_get_with_fallbacks_skips_unavailable(monkeypatch) -> None:
    """GET fallback continues after 404/422 and returns the first valid JSON."""
    service = LettaService()
    responses = [
        _build_response(422, content="invalid", method="GET"),
        _build_response(200, json_data={"items": []}, method="GET"),
    ]

    def _fake_get(*args, **kwargs) -> httpx.Response:
        return responses.pop(0)

    monkeypatch.setattr(httpx, "get", _fake_get)

    data = service._get_with_fallbacks([("http://letta.test/a", {}), ("http://letta.test/b", {})])

    assert data == {"items": []}
