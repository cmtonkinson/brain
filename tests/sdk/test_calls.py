"""Unit tests for Brain SDK call wrappers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from packages.brain_sdk.errors import BrainTransportError
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


def test_call_core_health_transport_error() -> None:
    """Core health wrapper should raise BrainTransportError on HTTP failure."""
    from packages.brain_sdk.calls import call_core_health

    transport_http = MagicMock()
    transport_http.get_json.side_effect = HttpStatusError(
        message="unavailable",
        method="GET",
        url="http://localhost/health",
        retryable=True,
        status_code=503,
        response_body="down",
        response_headers={},
    )

    with pytest.raises(BrainTransportError):
        call_core_health(
            http=transport_http,
            metadata=_meta(),
            timeout_seconds=1.0,
        )
