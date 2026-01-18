"""Contract tests for the Signal HTTP client."""

from __future__ import annotations

from datetime import datetime
import json

import pytest
import respx

from config import settings
from services.signal import SignalClient


@pytest.mark.asyncio
async def test_poll_messages_contract(monkeypatch) -> None:
    """Poll messages hits the receive endpoint and parses payloads."""
    monkeypatch.setattr(settings.signal, "url", "http://signal.test", raising=False)
    payload = [
        {
            "envelope": {
                "source": "+15550001111",
                "sourceDevice": 2,
                "dataMessage": {"message": "hello", "timestamp": 1_700_000_000_000},
            }
        }
    ]

    with respx.mock(assert_all_called=True) as router:
        route = router.get("http://signal.test/v1/receive/+15550001111").respond(200, json=payload)

        client = SignalClient(api_url="http://signal.test")
        messages = await client.poll_messages("+15550001111")

    assert route.called
    assert len(messages) == 1
    assert messages[0].sender == "+15550001111"
    assert messages[0].timestamp == datetime.fromtimestamp(1_700_000_000)


@pytest.mark.asyncio
async def test_send_message_contract(monkeypatch) -> None:
    """Send message posts the expected JSON payload."""
    monkeypatch.setattr(settings.signal, "url", "http://signal.test", raising=False)

    with respx.mock(assert_all_called=True) as router:
        route = router.post("http://signal.test/v2/send").respond(200, json={"ok": True})

        client = SignalClient(api_url="http://signal.test")
        ok = await client.send_message("+15550001111", "+15550002222", "hi")

    assert ok is True
    assert route.called
    request = route.calls[0].request
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content.decode("utf-8")) == {
        "message": "hi",
        "text_mode": "styled",
        "number": "+15550001111",
        "recipients": ["+15550002222"],
    }


@pytest.mark.asyncio
async def test_send_message_contract_handles_error(monkeypatch) -> None:
    """Send message returns False when the API responds with an error."""
    monkeypatch.setattr(settings.signal, "url", "http://signal.test", raising=False)

    with respx.mock(assert_all_called=True) as router:
        route = router.post("http://signal.test/v2/send").respond(500, json={"error": "fail"})

        client = SignalClient(api_url="http://signal.test")
        ok = await client.send_message("+15550001111", "+15550002222", "hi")

    assert ok is False
    assert route.called


@pytest.mark.asyncio
async def test_poll_messages_contract_handles_error(monkeypatch) -> None:
    """Poll messages returns an empty list on HTTP errors."""
    monkeypatch.setattr(settings.signal, "url", "http://signal.test", raising=False)

    with respx.mock(assert_all_called=True) as router:
        route = router.get("http://signal.test/v1/receive/+15550001111").respond(
            500, json={"error": "fail"}
        )

        client = SignalClient(api_url="http://signal.test")
        messages = await client.poll_messages("+15550001111")

    assert messages == []
    assert route.called


@pytest.mark.asyncio
async def test_get_accounts_contract(monkeypatch) -> None:
    """Get accounts issues a GET request to the accounts endpoint."""
    monkeypatch.setattr(settings.signal, "url", "http://signal.test", raising=False)

    with respx.mock(assert_all_called=True) as router:
        route = router.get("http://signal.test/v1/accounts").respond(
            200, json=[{"number": "+15550001111"}]
        )

        client = SignalClient(api_url="http://signal.test")
        accounts = await client.get_accounts()

    assert route.called
    assert accounts == [{"number": "+15550001111"}]


@pytest.mark.asyncio
async def test_check_connection_contract(monkeypatch) -> None:
    """Check connection returns True on a 200 response."""
    monkeypatch.setattr(settings.signal, "url", "http://signal.test", raising=False)

    with respx.mock(assert_all_called=True) as router:
        route = router.get("http://signal.test/v1/about").respond(200, json={"ok": True})

        client = SignalClient(api_url="http://signal.test")
        ok = await client.check_connection()

    assert route.called
    assert ok is True
