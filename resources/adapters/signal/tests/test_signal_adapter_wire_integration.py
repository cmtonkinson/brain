"""Wire-level Signal adapter tests against a local fake HTTP server."""

from __future__ import annotations

import pytest

from resources.adapters.signal.config import SignalAdapterSettings
from resources.adapters.signal.signal_adapter import (
    HttpSignalAdapter,
    SignalAdapterDependencyError,
)
from tests.helpers.fake_signal_server import FakeSignalServer


def test_send_message_posts_exact_v2_send_wire_payload() -> None:
    """Signal adapter should emit the exact expected `/v2/send` JSON payload."""
    with FakeSignalServer(status_code=201) as server:
        adapter = HttpSignalAdapter(
            settings=SignalAdapterSettings(
                base_url=server.base_url,
                receive_e164="+17175371552",
            )
        )

        result = adapter.send_message(
            sender_e164="+17175371552",
            recipient_e164="+16104257807",
            message="assistant reply",
        )

    assert result.delivered is True
    assert len(server.requests) == 1
    request = server.requests[0]
    assert request.path == "/v2/send"
    assert request.body == {
        "message": "assistant reply",
        "text_mode": "styled",
        "number": "+17175371552",
        "recipients": ["+16104257807"],
    }


def test_send_message_maps_400_status_to_dependency_error() -> None:
    """Signal adapter should surface HTTP 400 responses as dependency failures."""
    with FakeSignalServer(
        status_code=400,
        response_json={"error": "bad request"},
    ) as server:
        adapter = HttpSignalAdapter(
            settings=SignalAdapterSettings(
                base_url=server.base_url,
                receive_e164="+17175371552",
            )
        )

        with pytest.raises(SignalAdapterDependencyError, match="status 400"):
            adapter.send_message(
                sender_e164="+17175371552",
                recipient_e164="+16104257807",
                message="assistant reply",
            )
