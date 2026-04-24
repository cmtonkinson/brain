"""Reusable in-process Core smoke stack for agent end-to-end testing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import shutil
from pathlib import Path

from fastapi import APIRouter
from fastapi.testclient import TestClient

from actors.assistant import main as agent_main
from lib.sdk import (
    BrainClient,
    BrainSdkConfig,
    OpDescriptor,
    OpSearchHit,
)
from lib.shared.config import ActorSettings
from lib.shared.envelope import (
    Envelope,
    EnvelopeKind,
    Payload,
    new_meta,
    success,
)
from lib.shared.errors import ErrorDetail
from lib.shared.http.server import create_app
from resources.adapters.llm import (
    AdapterChatResult,
    AdapterEmbeddingResult,
    AdapterHealthResult,
    AdapterToolChatResult,
    LlmAdapter,
)
from resources.adapters.signal import (
    SignalAdapter,
    SignalCallbackRegistrationResult,
    SignalAdapterHealthResult,
    SignalInboundCallback,
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
from services.effect.execution.domain import OpInvokeResult
from services.effect.execution.implementation import (
    DefaultExecutionService,
)
from services.effect.execution.registry import OpRegistry
from services.effect.language.api import register_routes as register_language_routes
from services.effect.language.config import (
    LanguageEmbeddingProfileSettings,
    LanguageProfileSettings,
    LanguageServiceSettings,
)
from services.effect.language.implementation import DefaultLanguageService
from services.reason.policy.config import PolicyServiceSettings
from services.reason.policy.implementation import DefaultPolicyService
from services.effect.relay._inbound.api import (
    register_routes as register_inbound_routes,
)
from services.effect.relay._inbound.config import (
    RelayInboundIdentitySettings,
    RelayInboundServiceSettings,
)
from services.effect.relay._inbound.implementation import DefaultRelayInboundService
from services.state.cache.domain import HealthStatus, QueueDepth, QueueEntry
from services.state.cache.service import CacheService
from services.reason.recall.api import (
    register_routes as register_recall_routes,
)
from services.reason.recall.config import RecallSettings
from services.reason.recall.implementation import DefaultRecallService
from services.reason.recall.tests.test_recall_service import (
    _FakeMemoryRepository,
    _FakeRuntime,
)


class _FakeLlmAdapter(LlmAdapter):
    """Deterministic Language adapter fake for in-process smoke runs."""

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
        inference_request,
    ) -> AdapterToolChatResult:
        del provider, model
        self.tool_chat_tool_names.append(
            tuple(item.name for item in inference_request.tools)
        )
        return AdapterToolChatResult(
            text="assistant reply",
            tool_calls=(),
            provider="unit",
            model="test-model",
            finish_reason="stop",
        )

    def embed(
        self,
        *,
        provider: str,
        model: str,
        text: str,
        dimensions: int | None = None,
    ) -> AdapterEmbeddingResult:
        del provider, model, text, dimensions
        return AdapterEmbeddingResult(values=(0.1, 0.2), provider="unit", model="embed")

    def embed_batch(
        self, *, provider: str, model: str, texts, dimensions: int | None = None
    ):
        del provider, model, texts, dimensions
        raise NotImplementedError

    def health(self) -> AdapterHealthResult:
        return AdapterHealthResult(adapter_ready=True, detail="ok")


class _ScriptedLlmAdapter(LlmAdapter):
    """Scripted Language adapter fake for multi-round in-process smoke runs."""

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
        inference_request,
    ) -> AdapterToolChatResult:
        del provider, model
        self.tool_chat_tool_names.append(
            tuple(item.name for item in inference_request.tools)
        )
        if len(self._tool_chat_results) == 0:
            return AdapterToolChatResult(
                text="assistant reply",
                tool_calls=(),
                provider="unit",
                model="test-model",
                finish_reason="stop",
            )
        return self._tool_chat_results.pop(0)

    def embed(
        self,
        *,
        provider: str,
        model: str,
        text: str,
        dimensions: int | None = None,
    ) -> AdapterEmbeddingResult:
        del provider, model, text, dimensions
        return AdapterEmbeddingResult(values=(0.1, 0.2), provider="unit", model="embed")

    def embed_batch(
        self, *, provider: str, model: str, texts, dimensions: int | None = None
    ):
        del provider, model, texts, dimensions
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


class _SmokeCacheService(CacheService):
    """Queue-capable Cache fake for Relay inbound end-to-end smoke runs."""

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
    op_search_results: tuple[OpSearchHit, ...] = (),
    described_ops: tuple[OpDescriptor, ...] = (),
    extra_op_paths: tuple[Path, ...] = (),
    op_invoke_outputs: dict[str, dict[str, object] | None] | None = None,
) -> AgentE2ESmokeResult:
    """Run one inbound Signal message -> poll -> agent turn -> outbound send cycle."""
    app, signal, adapter = _build_core_app(
        tmp_path=tmp_path,
        tool_chat_results=tool_chat_results,
        op_search_results=op_search_results,
        described_ops=described_ops,
        extra_op_paths=extra_op_paths,
        op_invoke_outputs=op_invoke_outputs or {},
    )
    inbound = app.state.inbound_service
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
    inbound_result = inbound.ingest_signal_message(
        meta=new_meta(kind=EnvelopeKind.EVENT, source="test", principal="operator"),
        raw_body_json=body,
    )

    sdk_client = BrainClient(
        config=BrainSdkConfig(source="assistant", principal="operator"),
        http=_TestClientHttpAdapter(test_client),
    )
    runtime = agent_main._create_runtime(
        client=sdk_client,
        settings=ActorSettings(),
    )
    instruction = runtime.client.relay_poll_operator_instruction(
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
        tool_request_tool_names=tuple(adapter.tool_chat_tool_names),
    )


def _build_core_app(
    *,
    tmp_path: Path,
    tool_chat_results: tuple[AdapterToolChatResult, ...] = (),
    op_search_results: tuple[OpSearchHit, ...] = (),
    described_ops: tuple[OpDescriptor, ...] = (),
    extra_op_paths: tuple[Path, ...] = (),
    op_invoke_outputs: dict[str, dict[str, object] | None] | None = None,
):
    discovery_root = tmp_path / "ops"
    shutil.copytree(
        Path("ops/relay/relay-notify"),
        discovery_root / "relay-notify",
    )
    for op_path in extra_op_paths:
        shutil.copytree(op_path, discovery_root / op_path.name)

    signal = _FakeSignalAdapter()
    cache = _SmokeCacheService()
    inbound_settings = RelayInboundServiceSettings()
    inbound = DefaultRelayInboundService(
        settings=inbound_settings,
        identity=RelayInboundIdentitySettings(
            operator_signal_contact_e164="+16104257807",
            default_dial_code="+1",
        ),
        adapter=signal,
        cache_service=cache,
    )
    adapter: LlmAdapter = (
        _ScriptedLlmAdapter(tool_chat_results=tool_chat_results)
        if len(tool_chat_results) > 0
        else _FakeLlmAdapter()
    )
    language = DefaultLanguageService(
        settings=LanguageServiceSettings(
            document_embedding=LanguageEmbeddingProfileSettings(
                provider="unit", model="embed", dimensions=1024
            ),
            op_embedding=LanguageEmbeddingProfileSettings(
                provider="unit", model="embed-op", dimensions=1024
            ),
            quick=LanguageProfileSettings(provider="unit", model="quick"),
            standard=LanguageProfileSettings(provider="unit", model="standard"),
            deep=LanguageProfileSettings(provider="unit", model="deep"),
        ),
        adapter=adapter,
    )
    recall = DefaultRecallService(
        settings=RecallSettings(),
        runtime=_FakeRuntime(),
        repository=_FakeMemoryRepository(),
        language_model=language,
    )
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
    if len(op_search_results) > 0:
        execution.search_ops = lambda *, meta, query, limit=None: success(  # type: ignore[method-assign]
            meta=meta,
            payload=tuple(op_search_results),
        )
    if len(described_ops) > 0:
        descriptor_by_id = {item.op_id: item for item in described_ops}
        execution.describe_ops = lambda *, meta: success(  # type: ignore[method-assign]
            meta=meta,
            payload=tuple(described_ops),
        )
        execution.describe_op = lambda *, meta, op_id: success(  # type: ignore[method-assign]
            meta=meta,
            payload=descriptor_by_id[op_id],
        )
    invoke_outputs = op_invoke_outputs or {}
    if len(invoke_outputs) > 0:
        real_invoke_op = execution.invoke_op

        def _invoke_op(*, meta, op_id, input_payload, invocation):
            if op_id in invoke_outputs:
                return success(
                    meta=meta,
                    payload=OpInvokeResult(
                        op_id=op_id,
                        op_version="1.0.0",
                        output=invoke_outputs[op_id],
                        policy_decision_id="decision-smoke",
                        policy_regime_id="regime-smoke",
                        policy_allowed=True,
                        policy_reason_codes=(),
                        policy_obligations=(),
                        proposal_token="",
                    ),
                )
            return real_invoke_op(
                meta=meta,
                op_id=op_id,
                input_payload=input_payload,
                invocation=invocation,
            )

        execution.invoke_op = _invoke_op  # type: ignore[method-assign]
    execution_after_boot(
        settings=_settings(),
        components={
            "service_execution": execution,
            "service_relay": outbound,
        },
    )

    app = create_app()
    app.state.inbound_service = inbound
    router = APIRouter()
    register_inbound_routes(router=router, service=inbound)
    register_recall_routes(router=router, service=recall)
    register_language_routes(router=router, service=language)
    register_execution_routes(router=router, service=execution)
    app.include_router(router)
    return app, signal, adapter


def _ingest_result_body(result: Envelope[object]) -> dict[str, object]:
    """Serialize one direct Relay inbound ingest result into the old smoke shape."""
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
    from lib.shared.config import (
        CoreRuntimeSettings,
        CoreSettings,
        ResourcesSettings,
    )

    return CoreRuntimeSettings(core=CoreSettings(), resources=ResourcesSettings())
