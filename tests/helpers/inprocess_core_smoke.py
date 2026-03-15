"""Reusable in-process Core smoke stack for agent end-to-end testing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import shutil
from pathlib import Path

from fastapi import APIRouter
from fastapi.testclient import TestClient

from actors.agent import main as agent_main
from packages.brain_sdk import (
    BrainClient,
    BrainSdkConfig,
    CapabilityDescriptor,
    CapabilitySearchHit,
)
from packages.brain_shared.config import ActorSettings
from packages.brain_shared.config.models import ProfileSettings
from packages.brain_shared.envelope import (
    Envelope,
    EnvelopeKind,
    Payload,
    new_meta,
    success,
)
from packages.brain_shared.errors import ErrorDetail
from packages.brain_shared.http.server import create_app
from resources.adapters.litellm import (
    AdapterChatResult,
    AdapterChatMessage,
    AdapterChatToolDefinition,
    AdapterEmbeddingResult,
    AdapterHealthResult,
    AdapterToolChatResult,
    LiteLlmAdapter,
)
from resources.adapters.signal import (
    SignalAdapter,
    SignalCallbackRegistrationResult,
    SignalAdapterHealthResult,
    SignalInboundCallback,
    SignalSendMessageResult,
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
from services.action.capability_engine.domain import CapabilityInvokeResult
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

    def __init__(self) -> None:
        self.tool_chat_tool_names: list[tuple[str, ...]] = []

    def chat(self, *, provider: str, model: str, prompt: str) -> AdapterChatResult:
        del provider, model, prompt
        return AdapterChatResult(
            text="assistant reply",
            provider="unit",
            model="test-model",
        )

    def chat_batch(self, *, provider: str, model: str, prompts):
        raise NotImplementedError

    def chat_with_tools(
        self,
        *,
        provider: str,
        model: str,
        messages: tuple[AdapterChatMessage, ...],
        tools: tuple[AdapterChatToolDefinition, ...],
        tool_choice: str | dict[str, object] | None = None,
        parallel_tool_calls: bool | None = None,
    ) -> AdapterToolChatResult:
        del provider, model, messages, tool_choice, parallel_tool_calls
        self.tool_chat_tool_names.append(tuple(item.name for item in tools))
        return AdapterToolChatResult(
            text="assistant reply",
            tool_calls=(),
            provider="unit",
            model="test-model",
            finish_reason="stop",
        )

    def embed(self, *, provider: str, model: str, text: str) -> AdapterEmbeddingResult:
        del provider, model, text
        return AdapterEmbeddingResult(values=(0.1, 0.2), provider="unit", model="embed")

    def embed_batch(self, *, provider: str, model: str, texts):
        raise NotImplementedError

    def health(self) -> AdapterHealthResult:
        return AdapterHealthResult(adapter_ready=True, detail="ok")


class _ScriptedLiteLlmAdapter(LiteLlmAdapter):
    """Scripted LMS adapter fake for multi-round in-process smoke runs."""

    def __init__(
        self,
        *,
        tool_chat_results: tuple[AdapterToolChatResult, ...],
    ) -> None:
        self._tool_chat_results = list(tool_chat_results)
        self.tool_chat_tool_names: list[tuple[str, ...]] = []

    def chat(self, *, provider: str, model: str, prompt: str) -> AdapterChatResult:
        del provider, model, prompt
        return AdapterChatResult(
            text="assistant reply",
            provider="unit",
            model="test-model",
        )

    def chat_batch(self, *, provider: str, model: str, prompts):
        raise NotImplementedError

    def chat_with_tools(
        self,
        *,
        provider: str,
        model: str,
        messages: tuple[AdapterChatMessage, ...],
        tools: tuple[AdapterChatToolDefinition, ...],
        tool_choice: str | dict[str, object] | None = None,
        parallel_tool_calls: bool | None = None,
    ) -> AdapterToolChatResult:
        del provider, model, messages, tool_choice, parallel_tool_calls
        self.tool_chat_tool_names.append(tuple(item.name for item in tools))
        if len(self._tool_chat_results) == 0:
            return AdapterToolChatResult(
                text="assistant reply",
                tool_calls=(),
                provider="unit",
                model="test-model",
                finish_reason="stop",
            )
        return self._tool_chat_results.pop(0)

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

    def register_callback(
        self,
        *,
        callback: SignalInboundCallback,
    ) -> SignalCallbackRegistrationResult:
        del callback
        return SignalCallbackRegistrationResult(registered=True, detail="ok")

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
    tool_request_tool_names: tuple[tuple[str, ...], ...] = ()


def run_agent_e2e_smoke(
    *,
    tmp_path: Path,
    tool_chat_results: tuple[AdapterToolChatResult, ...] = (),
    capability_search_results: tuple[CapabilitySearchHit, ...] = (),
    described_capabilities: tuple[CapabilityDescriptor, ...] = (),
    extra_capability_paths: tuple[Path, ...] = (),
    capability_invoke_outputs: dict[str, dict[str, object] | None] | None = None,
) -> AgentE2ESmokeResult:
    """Run one inbound Signal message -> poll -> agent turn -> outbound send cycle."""
    app, signal, lms = _build_core_app(
        tmp_path=tmp_path,
        tool_chat_results=tool_chat_results,
        capability_search_results=capability_search_results,
        described_capabilities=described_capabilities,
        extra_capability_paths=extra_capability_paths,
        capability_invoke_outputs=capability_invoke_outputs or {},
    )
    switchboard = app.state.switchboard_service
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
    inbound_result = switchboard.ingest_signal_message(
        meta=new_meta(kind=EnvelopeKind.EVENT, source="test", principal="operator"),
        raw_body_json=body,
    )

    sdk_client = BrainClient(
        config=BrainSdkConfig(source="agent", principal="operator"),
        http=_TestClientHttpAdapter(test_client),
    )
    runtime = agent_main._create_runtime(
        client=sdk_client,
        settings=ActorSettings(),
    )
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
        inbound_status_code=202 if inbound_result.ok else 500,
        inbound_body=_ingest_result_body(inbound_result),
        response_text=response_text,
        outbound_signal_messages=tuple(signal.send_calls),
        tool_request_tool_names=tuple(lms.tool_chat_tool_names),
    )


def _build_core_app(
    *,
    tmp_path: Path,
    tool_chat_results: tuple[AdapterToolChatResult, ...] = (),
    capability_search_results: tuple[CapabilitySearchHit, ...] = (),
    described_capabilities: tuple[CapabilityDescriptor, ...] = (),
    extra_capability_paths: tuple[Path, ...] = (),
    capability_invoke_outputs: dict[str, dict[str, object] | None] | None = None,
):
    discovery_root = tmp_path / "capabilities"
    shutil.copytree(
        Path("capabilities/attention/attention-notify"),
        discovery_root / "attention-notify",
    )
    for capability_path in extra_capability_paths:
        shutil.copytree(capability_path, discovery_root / capability_path.name)

    signal = _FakeSignalAdapter()
    cache = _SmokeCacheService()
    switchboard_settings = SwitchboardServiceSettings()
    switchboard = DefaultSwitchboardService(
        settings=switchboard_settings,
        identity=SwitchboardIdentitySettings(
            operator_signal_contact_e164="+16104257807",
            default_dial_code="+1",
        ),
        adapter=signal,
        cache_service=cache,
    )
    adapter: LiteLlmAdapter = (
        _ScriptedLiteLlmAdapter(tool_chat_results=tool_chat_results)
        if len(tool_chat_results) > 0
        else _FakeLiteLlmAdapter()
    )
    lms = DefaultLanguageModelService(
        settings=LanguageModelServiceSettings(
            document_embedding=LanguageModelProfileSettings(
                provider="unit", model="embed"
            ),
            capability_embedding=LanguageModelProfileSettings(
                provider="unit", model="embed-capability"
            ),
            quick=LanguageModelProfileSettings(provider="unit", model="quick"),
            standard=LanguageModelProfileSettings(provider="unit", model="standard"),
            deep=LanguageModelProfileSettings(provider="unit", model="deep"),
        ),
        adapter=adapter,
    )
    memory = DefaultMemoryAuthorityService(
        settings=MemoryAuthoritySettings(),
        runtime=_FakeRuntime(),
        repository=_FakeMemoryRepository(),
        language_model=lms,
        profile=ProfileSettings(
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
    if len(capability_search_results) > 0:
        capability_engine.search_capabilities = lambda *, meta, query, limit=None: (
            success(  # type: ignore[method-assign]
                meta=meta,
                payload=tuple(capability_search_results),
            )
        )
    if len(described_capabilities) > 0:
        descriptor_by_id = {item.capability_id: item for item in described_capabilities}
        capability_engine.describe_capabilities = lambda *, meta: success(  # type: ignore[method-assign]
            meta=meta,
            payload=tuple(described_capabilities),
        )
        capability_engine.describe_capability = lambda *, meta, capability_id: success(  # type: ignore[method-assign]
            meta=meta,
            payload=descriptor_by_id[capability_id],
        )
    invoke_outputs = capability_invoke_outputs or {}
    if len(invoke_outputs) > 0:
        real_invoke_capability = capability_engine.invoke_capability

        def _invoke_capability(*, meta, capability_id, input_payload, invocation):
            if capability_id in invoke_outputs:
                return success(
                    meta=meta,
                    payload=CapabilityInvokeResult(
                        capability_id=capability_id,
                        capability_version="1.0.0",
                        output=invoke_outputs[capability_id],
                        policy_decision_id="decision-smoke",
                        policy_regime_id="regime-smoke",
                        policy_allowed=True,
                        policy_reason_codes=(),
                        policy_obligations=(),
                        proposal_token="",
                    ),
                )
            return real_invoke_capability(
                meta=meta,
                capability_id=capability_id,
                input_payload=input_payload,
                invocation=invocation,
            )

        capability_engine.invoke_capability = _invoke_capability  # type: ignore[method-assign]
    ces_after_boot(
        settings=_settings(),
        components={
            "service_capability_engine": capability_engine,
            "service_attention_router": attention_router,
        },
    )

    app = create_app()
    app.state.switchboard_service = switchboard
    router = APIRouter()
    register_switchboard_routes(router=router, service=switchboard)
    register_memory_routes(router=router, service=memory)
    register_lms_routes(router=router, service=lms)
    register_ces_routes(router=router, service=capability_engine)
    app.include_router(router)
    return app, signal, adapter


def _ingest_result_body(result: Envelope[object]) -> dict[str, object]:
    """Serialize one direct Switchboard ingest result into the old smoke shape."""
    payload = result.payload.value if result.payload is not None else None
    errors = result.errors
    return {
        "ok": result.ok,
        "accepted": False
        if payload is None
        else bool(getattr(payload, "accepted", False)),
        "queued": False if payload is None else bool(getattr(payload, "queued", False)),
        "reason": "" if payload is None else str(getattr(payload, "reason", "")),
        "errors": [_error_body(error) for error in errors],
    }


def _error_body(error: ErrorDetail) -> dict[str, object]:
    """Serialize one envelope error for smoke assertions."""
    category = error.category.value if error.category is not None else "unspecified"
    return {
        "code": error.code,
        "message": error.message,
        "category": category,
        "retryable": error.retryable,
        "metadata": error.metadata,
    }


def _settings():
    from packages.brain_shared.config import (
        CoreRuntimeSettings,
        CoreSettings,
        ResourcesSettings,
    )

    return CoreRuntimeSettings(core=CoreSettings(), resources=ResourcesSettings())
