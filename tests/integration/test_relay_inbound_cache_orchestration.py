"""Cross-service orchestration tests for Relay inbound->Cache behavior."""

from __future__ import annotations

import json

from lib.shared.envelope import EnvelopeKind, new_meta
from services.effect.relay._inbound.tests.test_inbound_integration import (
    _FakeCacheService,
    _FakeSignalAdapter,
)
from services.effect.relay._inbound.config import (
    RelayInboundIdentitySettings,
    RelayInboundServiceSettings,
)
from services.effect.relay._inbound.implementation import DefaultRelayInboundService


def _meta():
    """Build deterministic metadata for inbound Signal ingestion."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_signal_ingest_enqueues_message_in_cache() -> None:
    """Relay inbound should enqueue normalized operator message into Cache queue."""
    cache = _FakeCacheService()
    service = DefaultRelayInboundService(
        settings=RelayInboundServiceSettings(),
        identity=RelayInboundIdentitySettings(
            operator_signal_contact_e164="+12025550100",
            default_dial_code="+1",
        ),
        adapter=_FakeSignalAdapter(),
        cache_service=cache,
    )
    body = json.dumps(
        {
            "data": {
                "source": "+12025550100",
                "message": "hello",
                "timestamp": 1730000000000,
            }
        }
    )
    result = service.ingest_signal_message(
        meta=_meta(),
        raw_body_json=body,
    )

    assert result.ok is True
    assert len(cache.pushed) == 1
