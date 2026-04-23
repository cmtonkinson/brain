"""Cross-service orchestration tests for Switchboard->Cache Authority behavior."""

from __future__ import annotations

import json

from lib.shared.envelope import EnvelopeKind, new_meta
from services.action.switchboard.tests.test_switchboard_integration import (
    _FakeCacheService,
    _FakeSignalAdapter,
)
from services.action.switchboard.config import (
    SwitchboardIdentitySettings,
    SwitchboardServiceSettings,
)
from services.action.switchboard.implementation import DefaultSwitchboardService


def _meta():
    """Build deterministic metadata for inbound Signal ingestion."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_signal_ingest_enqueues_message_in_cache_authority() -> None:
    """Switchboard should enqueue normalized operator message into CAS queue."""
    cache = _FakeCacheService()
    service = DefaultSwitchboardService(
        settings=SwitchboardServiceSettings(),
        identity=SwitchboardIdentitySettings(
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
