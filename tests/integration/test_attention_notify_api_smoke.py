"""Fast integration tests for CES->Policy->Attention Router notify flow."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter
from fastapi.testclient import TestClient

from packages.brain_shared.http.server import create_app
from packages.brain_shared.ids import generate_ulid_str
from resources.adapters.signal import (
    SignalAdapter,
    SignalAdapterDependencyError,
    SignalAdapterHealthResult,
    SignalSendMessageResult,
    SignalWebhookRegistrationResult,
)
from services.action.attention_router.config import AttentionRouterServiceSettings
from services.action.attention_router.implementation import (
    DefaultAttentionRouterService,
)
from services.action.capability_engine.api import register_routes as register_ces_routes
from services.action.capability_engine.component import after_boot as ces_after_boot
from services.action.capability_engine.config import CapabilityEngineSettings
from services.action.capability_engine.data.repository import (
    InMemoryCapabilityInvocationAuditRepository,
)
from services.action.capability_engine.implementation import (
    DefaultCapabilityEngineService,
)
from services.action.capability_engine.registry import CapabilityRegistry
from services.action.policy_service.config import PolicyServiceSettings
from services.action.policy_service.implementation import DefaultPolicyService


class _FakeSignalAdapter(SignalAdapter):
    """Minimal Signal adapter fake for fast CES/AR integration tests."""

    def __init__(self) -> None:
        self.send_calls: list[dict[str, str]] = []
        self.raise_send: Exception | None = None

    def register_webhook(
        self,
        *,
        callback_url: str,
        shared_secret: str,
        operator_e164: str,
    ) -> SignalWebhookRegistrationResult:
        del callback_url, shared_secret, operator_e164
        return SignalWebhookRegistrationResult(registered=True, detail="ok")

    def health(self) -> SignalAdapterHealthResult:
        return SignalAdapterHealthResult(adapter_ready=True, detail="ok")

    def send_message(
        self,
        *,
        sender_e164: str,
        recipient_e164: str,
        message: str,
    ) -> SignalSendMessageResult:
        self.send_calls.append(
            {
                "sender_e164": sender_e164,
                "recipient_e164": recipient_e164,
                "message": message,
            }
        )
        if self.raise_send is not None:
            raise self.raise_send
        return SignalSendMessageResult(
            delivered=True,
            recipient_e164=recipient_e164,
            sender_e164=sender_e164,
            detail="delivered",
        )


def _client(tmp_path: Path) -> tuple[TestClient, _FakeSignalAdapter]:
    """Build a CES HTTP client wired to Policy and Attention Router in-process."""
    discovery_root = tmp_path / "capabilities"
    source_pkg = Path("capabilities/attention/attention-notify")
    shutil.copytree(source_pkg, discovery_root / "attention-notify")

    signal = _FakeSignalAdapter()
    attention_router = DefaultAttentionRouterService(
        settings=AttentionRouterServiceSettings(),
        signal_adapter=signal,
        operator_signal_contact_e164="+16104257807",
        signal_receive_e164="+17175371552",
    )
    policy = DefaultPolicyService(
        settings=PolicyServiceSettings(),
        attention_router_service=attention_router,
    )
    capability_engine = DefaultCapabilityEngineService(
        settings=CapabilityEngineSettings(discovery_root=str(discovery_root)),
        policy_service=policy,
        registry=CapabilityRegistry(),
        audit_repository=InMemoryCapabilityInvocationAuditRepository(),
    )
    components = {
        "service_capability_engine": capability_engine,
        "service_attention_router": attention_router,
    }
    ces_after_boot(settings=_settings(), components=components)

    app = create_app()
    router = APIRouter()
    register_ces_routes(router=router, service=capability_engine)
    app.include_router(router)
    return TestClient(app), signal


def test_attention_notify_api_smoke_delivers_outbound_signal_message(tmp_path) -> None:
    """Capability invoke HTTP should deliver one routed outbound via fake Signal."""
    client, signal = _client(tmp_path)

    response = client.post(
        "/capabilities/invoke",
        json={
            "source": "agent",
            "principal": "operator",
            "capability_id": "attention-notify",
            "input_payload": {
                "message": "assistant reply",
            },
            "actor": "operator",
            "channel": "signal",
            "invocation_id": generate_ulid_str(),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["errors"] == []
    assert json.loads(body["output_json"])["decision"] == "sent"
    assert signal.send_calls == [
        {
            "sender_e164": "+17175371552",
            "recipient_e164": "+16104257807",
            "message": "assistant reply",
        }
    ]


def test_attention_notify_api_smoke_returns_dependency_error_on_signal_failure(
    tmp_path,
) -> None:
    """Capability invoke HTTP should return dependency errors from Signal send failures."""
    client, signal = _client(tmp_path)
    signal.raise_send = SignalAdapterDependencyError(
        "signal send failed with status 400"
    )

    response = client.post(
        "/capabilities/invoke",
        json={
            "source": "agent",
            "principal": "operator",
            "capability_id": "attention-notify",
            "input_payload": {
                "message": "assistant reply",
            },
            "actor": "operator",
            "channel": "signal",
            "invocation_id": generate_ulid_str(),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["errors"][0]["category"] == "dependency"
    assert "signal send failed with status 400" in body["errors"][0]["message"]


def test_attention_notify_api_smoke_rejects_transport_identity_overrides(
    tmp_path,
) -> None:
    """Capability invoke HTTP should reject sender/recipient override fields."""
    client, _signal = _client(tmp_path)

    response = client.post(
        "/capabilities/invoke",
        json={
            "source": "agent",
            "principal": "operator",
            "capability_id": "attention-notify",
            "input_payload": {
                "message": "assistant reply",
                "sender_e164": "+17175371552",
                "recipient_e164": "+16104257807",
            },
            "actor": "operator",
            "channel": "signal",
            "invocation_id": generate_ulid_str(),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["errors"][0]["category"] == "validation"
    assert "unknown input keys" in body["errors"][0]["message"]


def _settings():
    """Return minimum inert settings object for CES after_boot wiring."""
    from packages.brain_shared.config import (
        CoreRuntimeSettings,
        CoreSettings,
        ResourcesSettings,
    )

    return CoreRuntimeSettings(core=CoreSettings(), resources=ResourcesSettings())
