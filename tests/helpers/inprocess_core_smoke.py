"""Reusable in-process Core smoke stack for agent end-to-end testing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import hmac
import json
import shutil
from pathlib import Path

from fastapi import APIRouter
from fastapi.testclient import TestClient

from actors.agent import main as agent_main
from packages.brain_sdk import BrainClient, BrainSdkConfig
from packages.brain_shared.config.models import ProfileSettings
from packages.brain_shared.envelope import Envelope, EnvelopeKind, Payload, new_meta
from resources.adapters.litellm import (
    AdapterChatResult,
    AdapterEmbeddingResult,
    AdapterHealthResult,
    LiteLlmAdapter,
)
from resources.adapters.signal import (
    SignalAdapter,
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
from services.action.language_model.api import register_routes as register_lms_routes
from services.action.language_model.config import (
    LanguageModelProfileSettings,
    LanguageModelServiceSettings,
)
from services.action.language_model.implementation import DefaultLanguageModelService
from services.action.policy_service.config import PolicyServiceSettings
from services.action.policy_service.implementation import DefaultPolicyService
from services.action.switchboard.api import (
    register_routes as register_switchboard_routes,
)
from services.action.switchboard.config import (
    SwitchboardIdentitySettings,
    SwitchboardServiceSettings,
)
from services.action.switchboard.http_ingress import create_switchboard_webhook_app
from services.action.switchboard.implementation import DefaultSwitchboardService
from services.state.cache_authority.domain import HealthStatus, QueueDepth, QueueEntry
from services.state.cache_authority.service import CacheAuthorityService
from services.state.memory_authority.api import (
    register_routes as register_memory_routes,
)
from services.state.memory_authority.config import MemoryAuthoritySettings
from services.state.memory_authority.implementation import DefaultMemoryAuthorityService
from services.state.memory_authority.tests.test_memory_authority_service import (
    _FakeMemoryRepository,
    _FakeRuntime,
)


class _FakeLiteLlmAdapter(LiteLlmAdapter):
    """Deterministic LMS adapter fake for in-process smoke runs."""

    def chat(self, *, provider: str, model: str, prompt: str) -> AdapterChatResult:
        del provider, model, prompt
        return AdapterChatResult(
            text='{"kind":"final","content":"assistant reply"}',
            provider="unit",
            model="test-model",
        )

    def chat_batch(self, *, provider: str, model: str, prompts):
        raise NotImplementedError

    def embed(self, *, provider: str, model: str, text: str) -> AdapterEmbeddingResult:
        del provider, model, text
        return AdapterEmbeddingResult(values=(0.1, 0.2), provider="unit", model="embed")

    def embed_batch(self, *, provider: str, model: str, texts):
        raise NotImplementedError

    def health(self) -> AdapterHealthResult:
        return AdapterHealthResult(adapter_ready=True, detail="ok")


class _FakeSignalAdapter(SignalAdapter):
    """Signal adapter fake that records outbound sends."""

    def __init__(self) -> None:
        self.send_calls: list[dict[str, str]] = []

    def register_webhook(
        self,
        *,
        callback_url: str,
        shared_secret: str,
    ) -> SignalWebhookRegistrationResult:
        del callback_url, shared_secret
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
        return SignalSendMessageResult(
            delivered=True,
            recipient_e164=recipient_e164,
            sender_e164=sender_e164,
            detail="sent",
        )


class _SmokeCacheService(CacheAuthorityService):
    """Queue-capable CAS fake for Switchboard end-to-end smoke runs."""

    def __init__(self) -> None:
        self._queues: dict[tuple[str, str], list[object]] = {}

    def set_value(self, *, meta, component_id, key, value, ttl_seconds=None):
        raise NotImplementedError

    def get_value(self, *, meta, component_id, key):
        raise NotImplementedError

    def delete_value(self, *, meta, component_id, key):
        raise NotImplementedError

    def push_queue(self, *, meta, component_id: str, queue: str, value):
        items = self._queues.setdefault((component_id, queue), [])
        items.append(value)
        return Envelope(
            metadata=meta,
            payload=Payload(
                value=QueueDepth(
                    component_id=component_id, queue=queue, size=len(items)
                )
            ),
            errors=[],
        )

    def pop_queue(self, *, meta, component_id: str, queue: str):
        items = self._queues.setdefault((component_id, queue), [])
        if not items:
            return Envelope(metadata=meta, payload=Payload(value=None), errors=[])
        return Envelope(
            metadata=meta,
            payload=Payload(
                value=QueueEntry(
                    component_id=component_id,
                    queue=queue,
                    value=items.pop(0),
                )
            ),
            errors=[],
        )

    def peek_queue(self, *, meta, component_id: str, queue: str):
        items = self._queues.setdefault((component_id, queue), [])
        if not items:
            return Envelope(metadata=meta, payload=Payload(value=None), errors=[])
        return Envelope(
            metadata=meta,
            payload=Payload(
                value=QueueEntry(
                    component_id=component_id,
                    queue=queue,
                    value=items[0],
                )
            ),
            errors=[],
        )

    def health(self, *, meta):
        return Envelope(
            metadata=meta,
            payload=Payload(
                value=HealthStatus(
                    service_ready=True,
                    substrate_ready=True,
                    detail="ok",
                )
            ),
            errors=[],
        )


class _TestClientHttpAdapter:
    """Minimal HTTP adapter that lets BrainClient talk to a FastAPI TestClient."""

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def close(self) -> None:
        return

    def post_json(self, url: str, *, json: dict[str, object], **_kwargs):
        response = self._client.post(url, json=json)
        response.raise_for_status()
        return response.json()

    def get_json(self, url: str, **_kwargs):
        response = self._client.get(url)
        response.raise_for_status()
        return response.json()


@dataclass(frozen=True, slots=True)
class AgentE2ESmokeResult:
    """Captured result for one in-process end-to-end agent smoke run."""

    inbound_status_code: int
    inbound_body: dict[str, object]
    response_text: str
    outbound_signal_messages: tuple[dict[str, str], ...]


def run_agent_e2e_smoke(*, tmp_path: Path) -> AgentE2ESmokeResult:
    """Run one inbound webhook -> poll -> agent turn -> outbound send cycle."""
    app, signal = _build_core_app(tmp_path=tmp_path)
    test_client = TestClient(app)

    body = json.dumps(
        {
            "data": {
                "account": "+17175371552",
                "envelope": {
                    "source": "+16104257807",
                    "sourceDevice": 1,
                    "timestamp": 1730000000000,
                    "dataMessage": {"message": "hello"},
                },
            }
        }
    )
    timestamp = int(
        new_meta(
            kind=EnvelopeKind.EVENT, source="test", principal="operator"
        ).timestamp.timestamp()
    )
    inbound = test_client.post(
        "/v1/inbound/signal/webhook",
        content=body,
        headers={
            "X-Brain-Timestamp": str(timestamp),
            "X-Brain-Signature": _signature("secret", timestamp, body),
            "Content-Type": "application/json",
        },
    )

    sdk_client = BrainClient(
        config=BrainSdkConfig(source="agent", principal="operator"),
        http=_TestClientHttpAdapter(test_client),
    )
    runtime = agent_main._create_runtime(client=sdk_client)
    instruction = runtime.client.switchboard_poll_operator_instruction(
        wait_timeout_seconds=0.0
    )
    assert instruction is not None
    response_text = asyncio.run(
        agent_main._process_instruction(
            runtime=runtime,
            instruction=instruction,
        )
    )
    sdk_client.close()
    test_client.close()
    return AgentE2ESmokeResult(
        inbound_status_code=inbound.status_code,
        inbound_body=inbound.json(),
        response_text=response_text,
        outbound_signal_messages=tuple(signal.send_calls),
    )


def _build_core_app(*, tmp_path: Path):
    discovery_root = tmp_path / "capabilities"
    shutil.copytree(
        Path("capabilities/attention/attention-notify"),
        discovery_root / "attention-notify",
    )

    signal = _FakeSignalAdapter()
    cache = _SmokeCacheService()
    switchboard_settings = SwitchboardServiceSettings(
        signature_tolerance_seconds=300,
        webhook_path="/v1/inbound/signal/webhook",
    )
    switchboard = DefaultSwitchboardService(
        settings=switchboard_settings,
        identity=SwitchboardIdentitySettings(
            operator_signal_contact_e164="+16104257807",
            default_dial_code="+1",
            webhook_shared_secret="secret",
        ),
        adapter=signal,
        cache_service=cache,
    )
    lms = DefaultLanguageModelService(
        settings=LanguageModelServiceSettings(
            embedding=LanguageModelProfileSettings(provider="unit", model="embed"),
            quick=LanguageModelProfileSettings(provider="unit", model="quick"),
            standard=LanguageModelProfileSettings(provider="unit", model="standard"),
            deep=LanguageModelProfileSettings(provider="unit", model="deep"),
        ),
        adapter=_FakeLiteLlmAdapter(),
    )
    memory = DefaultMemoryAuthorityService(
        settings=MemoryAuthoritySettings(),
        runtime=_FakeRuntime(),
        repository=_FakeMemoryRepository(),
        language_model=lms,
        profile=ProfileSettings(
            webhook_shared_secret="secret",
            operator_name="Operator",
            brain_name="Brain",
            brain_verbosity="normal",
        ),
    )
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
    ces_after_boot(
        settings=_settings(),
        components={
            "service_capability_engine": capability_engine,
            "service_attention_router": attention_router,
        },
    )

    app = create_switchboard_webhook_app(
        service=switchboard, settings=switchboard_settings
    )
    router = APIRouter()
    register_switchboard_routes(router=router, service=switchboard)
    register_memory_routes(router=router, service=memory)
    register_lms_routes(router=router, service=lms)
    register_ces_routes(router=router, service=capability_engine)
    app.include_router(router)
    return app, signal


def _signature(secret: str, timestamp: int, body: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{body}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _settings():
    from packages.brain_shared.config import (
        CoreRuntimeSettings,
        CoreSettings,
        ResourcesSettings,
    )

    return CoreRuntimeSettings(core=CoreSettings(), resources=ResourcesSettings())
