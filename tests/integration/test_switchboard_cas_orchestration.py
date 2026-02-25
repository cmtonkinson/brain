"""Cross-service orchestration tests for Switchboard->Cache Authority behavior."""

from __future__ import annotations

import hashlib
import hmac
import json

from packages.brain_shared.envelope import EnvelopeKind, new_meta
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
    """Build deterministic metadata for webhook ingestion."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def _signature(secret: str, timestamp: int, body: str) -> str:
    """Return valid signature header for a webhook payload."""
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{body}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def test_webhook_ingest_enqueues_message_in_cache_authority() -> None:
    """Switchboard should enqueue normalized operator message into CAS queue."""
    cache = _FakeCacheService()
    service = DefaultSwitchboardService(
        settings=SwitchboardServiceSettings(signature_tolerance_seconds=300),
        identity=SwitchboardIdentitySettings(
            operator_signal_e164="+12025550100",
            default_country_code="US",
            webhook_shared_secret="secret",
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
    now_ts = int(_meta().timestamp.timestamp())
    result = service.ingest_signal_webhook(
        meta=_meta(),
        raw_body_json=body,
        header_timestamp=str(now_ts),
        header_signature=_signature("secret", now_ts, body),
    )

    assert result.ok is True
    assert len(cache.pushed) == 1
