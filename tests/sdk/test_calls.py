"""Unit tests for Brain SDK call wrappers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from packages.brain_sdk.errors import BrainTransportError, BrainValidationError
from packages.brain_shared.http.errors import HttpStatusError


def _meta() -> dict[str, object]:
    from packages.brain_sdk.meta import build_envelope_meta

    return build_envelope_meta(source="tests", principal="operator")


def _fake_http(response: object) -> MagicMock:
    """Return a mock HttpClient that returns response from get_json/post_json."""
    http = MagicMock()
    http.get_json.return_value = response
    http.post_json.return_value = response
    return http


def test_call_core_health_success() -> None:
    """Core health wrapper should return mapped component dictionaries."""
    from packages.brain_sdk.calls import call_core_health

    http = _fake_http(
        {
            "ready": True,
            "services": {"svc": {"ready": True, "detail": "ok"}},
            "resources": {"res": {"ready": False, "detail": "degraded"}},
        }
    )

    result = call_core_health(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
    )

    assert result.ready is True
    assert result.services["svc"].detail == "ok"
    assert result.resources["res"].ready is False


def test_call_lms_chat_success() -> None:
    """Chat wrapper should return simple chat payload dataclass."""
    from packages.brain_sdk.calls import call_lms_chat

    http = _fake_http(
        {
            "payload": {"text": "hello", "provider": "local", "model": "model-a"},
            "errors": [],
        }
    )

    result = call_lms_chat(
        http=http,
        metadata=_meta(),
        prompt="hi",
        profile="standard",
        timeout_seconds=1.0,
    )

    assert result.text == "hello"
    assert result.provider == "local"
    assert result.model == "model-a"


def test_call_vault_get_success() -> None:
    """Vault get wrapper should map file payload to dataclass."""
    from packages.brain_sdk.calls import call_vault_get

    ts = "2026-02-26T16:00:00+00:00"
    http = _fake_http(
        {
            "payload": {
                "path": "notes/today.md",
                "content": "content",
                "size_bytes": 7,
                "created_at": ts,
                "updated_at": ts,
                "revision": "r1",
            },
            "errors": [],
        }
    )

    file_record = call_vault_get(
        http=http,
        metadata=_meta(),
        file_path="notes/today.md",
        timeout_seconds=1.0,
    )

    assert file_record.path == "notes/today.md"
    assert file_record.content == "content"


def test_call_vault_list_success() -> None:
    """Vault list wrapper should map list payload to dataclass list."""
    from packages.brain_sdk.calls import call_vault_list

    ts = "2026-02-26T16:00:00+00:00"
    http = _fake_http(
        {
            "payload": [
                {
                    "path": "notes/today.md",
                    "name": "today.md",
                    "entry_type": "file",
                    "size_bytes": 7,
                    "created_at": ts,
                    "updated_at": ts,
                    "revision": "r1",
                }
            ],
            "errors": [],
        }
    )

    entries = call_vault_list(
        http=http,
        metadata=_meta(),
        directory_path="notes",
        timeout_seconds=1.0,
    )

    assert entries[0].entry_type == "file"


def test_call_vault_search_success() -> None:
    """Vault search wrapper should map search results to dataclass list."""
    from packages.brain_sdk.calls import call_vault_search

    ts = "2026-02-26T16:00:00+00:00"
    http = _fake_http(
        {
            "payload": [
                {
                    "path": "notes/today.md",
                    "score": 0.9,
                    "snippets": ["today"],
                    "updated_at": ts,
                    "revision": "r1",
                }
            ],
            "errors": [],
        }
    )

    matches = call_vault_search(
        http=http,
        metadata=_meta(),
        query="today",
        directory_scope="notes",
        limit=5,
        timeout_seconds=1.0,
    )

    assert matches[0].snippets == ("today",)


def test_call_wrappers_raise_domain_and_transport_errors() -> None:
    """Wrappers should raise typed domain and transport failures."""
    from packages.brain_sdk.calls import call_lms_chat, call_vault_get

    domain_http = _fake_http(
        {
            "errors": [
                {
                    "code": "INVALID_ARGUMENT",
                    "message": "prompt required",
                    "category": "validation",
                    "retryable": False,
                }
            ]
        }
    )

    with pytest.raises(BrainValidationError):
        call_lms_chat(
            http=domain_http,
            metadata=_meta(),
            prompt="",
            profile="standard",
            timeout_seconds=1.0,
        )

    transport_http = MagicMock()
    transport_http.post_json.side_effect = HttpStatusError(
        message="unavailable",
        method="POST",
        url="http://localhost/vault/files/get",
        retryable=True,
        status_code=503,
        response_body="down",
        response_headers={},
    )

    with pytest.raises(BrainTransportError):
        call_vault_get(
            http=transport_http,
            metadata=_meta(),
            file_path="notes/today.md",
            timeout_seconds=1.0,
        )
