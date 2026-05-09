"""Cross-service orchestration tests for Relay inbound->Cache behavior."""

from __future__ import annotations

from lib.shared.envelope import EnvelopeKind, new_meta
from lib.shared.inbound_message import InboundMessage, InboundSender
from services.effect.relay._inbound.tests.test_inbound_service import (
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
            operator_contact_e164="+12025550100",
            default_dial_code="+1",
        ),
        inbound_adapters=(_FakeSignalAdapter(),),
        cache_service=cache,
    )
    result = service.ingest_inbound_message(
        meta=_meta(),
        message=InboundMessage(
            channel="signal",
            sender=InboundSender(e164="+12025550100"),
            message_text="hello",
            timestamp_ms=1730000000000,
        ),
    )

    assert result.ok is True
    assert len(cache.queue_calls) == 1
