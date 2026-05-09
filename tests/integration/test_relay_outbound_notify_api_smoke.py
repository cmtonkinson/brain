"""Fast integration tests for Execution->Policy->Relay outbound notify flow."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter
from fastapi.testclient import TestClient

from lib.shared.http.server import create_app
from lib.shared.ids import generate_ulid_str
from lib.shared.inbound_adapter import (
    InboundAdapterHealthResult,
    InboundCallback,
    InboundCallbackRegistrationResult,
)
from resources.adapters.signal import (
    SignalAdapter,
    SignalAdapterDependencyError,
    SignalSendMessageResult,
)
from services.effect.relay._outbound.config import RelayOutboundServiceSettings
from services.effect.relay._outbound.implementation import (
    DefaultRelayOutboundService,
)
from services.effect.execution.api import register_routes as register_execution_routes
from services.effect.execution.component import after_boot as execution_after_boot
from services.effect.execution.config import ExecutionSettings
from services.effect.execution.data.repository import (
    InMemoryOpInvocationAuditRepository,
)
from services.effect.execution.implementation import (
    DefaultExecutionService,
)
from services.effect.execution.registry import OpRegistry
from services.reason.policy.config import PolicyServiceSettings
from services.reason.policy.implementation import DefaultPolicyService


class _FakeSignalAdapter(SignalAdapter):
    """Minimal Signal adapter fake for fast Execution/Relay outbound integration tests."""

    def __init__(self) -> None:
        self.send_calls: list[dict[str, str]] = []
        self.raise_send: Exception | None = None

    def register_callback(
        self,
        *,
        callback: InboundCallback,
    ) -> InboundCallbackRegistrationResult:
        del callback
        return InboundCallbackRegistrationResult(registered=True, detail="ok")

    def health(self) -> InboundAdapterHealthResult:
        return InboundAdapterHealthResult(adapter_ready=True, detail="ok")

    def mint_slash_authenticity_proof(self, *, channel: str, message_text: str):
        del channel, message_text
        raise NotImplementedError

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
    """Build a Execution HTTP client wired to Policy and Relay outbound in-process."""
    discovery_root = tmp_path / "ops"
    source_pkg = Path("ops/relay/relay-notify")
    shutil.copytree(source_pkg, discovery_root / "relay-notify")

    signal = _FakeSignalAdapter()
    outbound = DefaultRelayOutboundService(
        settings=RelayOutboundServiceSettings(),
        signal_adapter=signal,
        operator_signal_contact_e164="+16104257807",
        signal_receive_e164="+17175371552",
        console_response_queue_name="console_outbound",
    )
    policy = DefaultPolicyService(
        settings=PolicyServiceSettings(),
        outbound_service=outbound,
    )
    execution = DefaultExecutionService(
        settings=ExecutionSettings(discovery_roots=(str(discovery_root),)),
        policy_service=policy,
        registry=OpRegistry(),
        audit_repository=InMemoryOpInvocationAuditRepository(),
    )
    components = {
        "service_execution": execution,
        "service_relay": outbound,
    }
    execution_after_boot(settings=_settings(), components=components)

    app = create_app()
    router = APIRouter()
    register_execution_routes(router=router, service=execution)
    app.include_router(router)
    return TestClient(app), signal


def test_relay_outbound_notify_api_smoke_delivers_outbound_signal_message(
    tmp_path,
) -> None:
    """Op invoke HTTP should deliver one routed outbound via fake Signal."""
    client, signal = _client(tmp_path)

    response = client.post(
        "/ops/invoke",
        json={
            "source": "agent",
            "principal": "operator",
            "op_id": "relay-notify",
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


def test_relay_outbound_notify_api_smoke_returns_dependency_error_on_signal_failure(
    tmp_path,
) -> None:
    """Op invoke HTTP should return dependency errors from Signal send failures."""
    client, signal = _client(tmp_path)
    signal.raise_send = SignalAdapterDependencyError(
        "signal send failed with status 400"
    )

    response = client.post(
        "/ops/invoke",
        json={
            "source": "agent",
            "principal": "operator",
            "op_id": "relay-notify",
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


def test_relay_outbound_notify_api_smoke_rejects_transport_identity_overrides(
    tmp_path,
) -> None:
    """Op invoke HTTP should reject sender/recipient override fields."""
    client, _signal = _client(tmp_path)

    response = client.post(
        "/ops/invoke",
        json={
            "source": "agent",
            "principal": "operator",
            "op_id": "relay-notify",
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
    """Return minimum inert settings object for Execution after_boot wiring."""
    from lib.shared.config import (
        CoreRuntimeSettings,
        CoreSettings,
        ResourcesSettings,
    )

    return CoreRuntimeSettings(core=CoreSettings(), resources=ResourcesSettings())
