"""Reusable in-process harness for one Brain Assistant turn over mock Core HTTP."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from types import SimpleNamespace
from typing import Any, cast

import httpx

from lib.agent import operator_runtime
from lib.sdk import (
    BrainClient,
    BrainSdkConfig,
    OpDescriptor,
    OpSearchHit,
    LmsToolChatResult,
    MemoryContextBlock,
    MemoryDialogueTurn,
    RelayOperatorInstruction,
    ToolSystemHint,
)
from lib.shared.http.client import HttpClient
from lib.shared.ids import generate_ulid_str
from lib.shared.config import ActorSettings, CoreSettings


@dataclass(frozen=True, slots=True)
class MockCoreCall:
    """One captured SDK->Core request made during a harness run."""

    method: str
    path: str
    body: dict[str, Any]


@dataclass(slots=True)
class AgentTurnScenario:
    """Configurable input/output scenario for one in-process agent turn."""

    session_id: str = field(default_factory=generate_ulid_str)
    ops: tuple[OpDescriptor, ...] = ()
    always_on_ops: tuple[OpDescriptor, ...] = ()
    tool_system_hints: tuple[ToolSystemHint, ...] = ()
    search_results: tuple[OpSearchHit, ...] = ()
    described_ops: dict[str, OpDescriptor] = field(default_factory=dict)
    instruction: RelayOperatorInstruction = field(
        default_factory=lambda: RelayOperatorInstruction(
            sender_e164="+12025550100",
            message_text="hello",
            timestamp_ms=1,
            source_device="1",
            source="signal",
            group_id=None,
            quote_target_timestamp_ms=None,
            reaction_target_timestamp_ms=None,
            reaction_emoji=None,
            approval_intent=None,
        )
    )
    context: MemoryContextBlock = field(
        default_factory=lambda: MemoryContextBlock(
            current_focus="current focus",
            recent_conversation_summary="prior summary",
            recent_turns=(
                MemoryDialogueTurn(
                    role="user",
                    content="hello",
                    is_summary=False,
                ),
            ),
            reference_snippets=(),
        )
    )
    chat_result: LmsToolChatResult = field(
        default_factory=lambda: LmsToolChatResult(
            provider="unit",
            model="test-model",
            finish_reason="stop",
            text="assistant reply",
            tool_calls=(),
        )
    )
    chat_results: tuple[LmsToolChatResult, ...] = ()
    op_invoke_outputs: dict[str, dict[str, Any] | None] = field(
        default_factory=lambda: {"relay-notify": {"decision": "sent"}}
    )
    op_invoke_errors: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentTurnRunResult:
    """Captured outcome for one agent turn harness execution."""

    response_text: str
    calls: tuple[MockCoreCall, ...]


def run_agent_turn_scenario(scenario: AgentTurnScenario) -> AgentTurnRunResult:
    """Run one full agent turn against a mock Core HTTP transport."""
    calls: list[MockCoreCall] = []
    remaining_chat_results = list(scenario.chat_results)

    def _response_for(request: httpx.Request) -> httpx.Response:
        body = _decode_request_json(request)
        calls.append(
            MockCoreCall(
                method=request.method,
                path=request.url.path,
                body=body,
            )
        )
        path = request.url.path
        if path in ("/memory/get_latest_or_create_session", "/memory/create_session"):
            return _json_response(
                request,
                {
                    "session_id": scenario.session_id,
                    "errors": [],
                },
            )
        if path == "/ops/describe":
            return _json_response(
                request,
                {
                    "ops": [
                        {
                            "op_id": item.op_id,
                            "kind": item.kind,
                            "version": item.version,
                            "summary": item.summary,
                            "input_schema": item.input_schema,
                            "output_schema": item.output_schema,
                            "effect": item.effect,
                            "approval": item.approval,
                            "required_ops": list(item.required_ops),
                        }
                        for item in scenario.ops
                    ],
                    "errors": [],
                },
            )
        if path == "/ops/always-on":
            return _json_response(
                request,
                {
                    "ops": [
                        {
                            "op_id": item.op_id,
                            "kind": item.kind,
                            "version": item.version,
                            "summary": item.summary,
                            "input_schema": item.input_schema,
                            "output_schema": item.output_schema,
                            "effect": item.effect,
                            "approval": item.approval,
                            "required_ops": list(item.required_ops),
                        }
                        for item in scenario.always_on_ops
                    ],
                    "errors": [],
                },
            )
        if path == "/ops/search":
            return _json_response(
                request,
                {
                    "results": [
                        {
                            "op_id": item.op_id,
                            "required_params": list(item.required_params),
                            "summary": item.summary,
                        }
                        for item in scenario.search_results
                    ],
                    "errors": [],
                },
            )
        if path == "/ops/tool-system-hints":
            return _json_response(
                request,
                {
                    "systems": [
                        {
                            "system_id": item.system_id,
                            "label": item.label,
                            "summary": item.summary,
                            "kind": item.kind,
                            "ready": item.ready,
                            "tool_count": item.tool_count,
                        }
                        for item in scenario.tool_system_hints
                    ],
                    "errors": [],
                },
            )
        if path == "/ops/describe-one":
            op_id = str(body.get("op_id", "")).strip()
            descriptor = scenario.described_ops.get(op_id)
            return _json_response(
                request,
                {
                    "op": (
                        None
                        if descriptor is None
                        else {
                            "op_id": descriptor.op_id,
                            "kind": descriptor.kind,
                            "version": descriptor.version,
                            "summary": descriptor.summary,
                            "input_schema": descriptor.input_schema,
                            "output_schema": descriptor.output_schema,
                            "effect": descriptor.effect,
                            "approval": descriptor.approval,
                            "required_ops": list(descriptor.required_ops),
                        }
                    ),
                    "errors": [],
                },
            )
        if path == "/memory/assemble_context":
            return _json_response(
                request,
                {
                    "payload": {
                        "session_id": scenario.session_id,
                        "inbound_turn": {
                            "id": generate_ulid_str(),
                            "session_id": scenario.session_id,
                            "direction": "inbound",
                            "content": str(body.get("message", "")),
                            "role": "user",
                            "model": None,
                            "provider": None,
                            "token_count": 3,
                            "reasoning_level": None,
                            "trace_id": body.get("trace_id", ""),
                            "conversation_episode_id": generate_ulid_str(),
                            "principal": body.get("principal", ""),
                            "created_at": "2026-04-12T00:00:00+00:00",
                        },
                        "context": {
                            "current_focus": scenario.context.current_focus,
                            "recent_conversation_summary": (
                                scenario.context.recent_conversation_summary
                            ),
                            "recent_turns": [
                                {
                                    "role": turn.role,
                                    "content": turn.content,
                                    "is_summary": turn.is_summary,
                                }
                                for turn in scenario.context.recent_turns
                            ],
                            "reference_snippets": list(
                                scenario.context.reference_snippets
                            ),
                        },
                    },
                    "errors": [],
                },
            )
        if path == "/memory/record_inbound_turn":
            return _json_response(
                request,
                {
                    "payload": {
                        "id": generate_ulid_str(),
                        "session_id": scenario.session_id,
                        "direction": "inbound",
                        "content": str(body.get("message", "")),
                        "role": "user",
                        "model": None,
                        "provider": None,
                        "token_count": 3,
                        "reasoning_level": None,
                        "trace_id": body.get("trace_id", ""),
                        "conversation_episode_id": generate_ulid_str(),
                        "principal": body.get("principal", ""),
                        "created_at": "2026-04-12T00:00:00+00:00",
                    },
                    "errors": [],
                },
            )
        if path == "/memory/assemble_snapshot":
            return _json_response(
                request,
                {
                    "payload": {
                        "current_focus": scenario.context.current_focus,
                        "recent_conversation_summary": (
                            scenario.context.recent_conversation_summary
                        ),
                        "recent_turns": [
                            {
                                "role": turn.role,
                                "content": turn.content,
                                "is_summary": turn.is_summary,
                            }
                            for turn in scenario.context.recent_turns
                        ],
                        "reference_snippets": list(scenario.context.reference_snippets),
                    },
                    "errors": [],
                },
            )
        if path == "/memory/record_outbound_candidate":
            content = str(body.get("content", ""))
            return _json_response(
                request,
                {
                    "payload": {
                        "id": generate_ulid_str(),
                        "session_id": scenario.session_id,
                        "direction": "outbound",
                        "content": content,
                        "role": "assistant",
                        "model": str(body.get("model", "")),
                        "provider": str(body.get("provider", "")),
                        "token_count": int(body.get("token_count", 0)),
                        "reasoning_level": str(body.get("reasoning_level", "")),
                        "trace_id": body.get("trace_id", ""),
                        "conversation_episode_id": "",
                        "principal": body.get("principal", ""),
                        "created_at": "2026-04-12T00:00:00+00:00",
                    },
                    "errors": [],
                },
            )
        if path == "/memory/record_outbound_delivery":
            return _json_response(
                request,
                {
                    "payload": bool(body.get("delivered", False)),
                    "errors": [],
                },
            )
        if path == "/lms/chat-with-tools":
            chat_result = (
                remaining_chat_results.pop(0)
                if len(remaining_chat_results) > 0
                else scenario.chat_result
            )
            return _json_response(
                request,
                {
                    "payload": {
                        "provider": chat_result.provider,
                        "model": chat_result.model,
                        "finish_reason": chat_result.finish_reason,
                        "text": chat_result.text,
                        "tool_calls": [
                            {
                                "tool_name": item.tool_name,
                                "args_json": item.args_json,
                                "tool_call_id": item.tool_call_id,
                            }
                            for item in chat_result.tool_calls
                        ],
                    },
                    "errors": [],
                },
            )
        if path == "/memory/record_response":
            return _json_response(request, {"payload": True, "errors": []})
        if path == "/ops/invoke":
            op_id = str(body.get("op_id", "")).strip()
            output = scenario.op_invoke_outputs.get(op_id)
            errors = scenario.op_invoke_errors.get(op_id, [])
            return _json_response(
                request,
                {
                    "output_json": ("" if output is None else json.dumps(output)),
                    "policy": {
                        "decision_id": generate_ulid_str(),
                        "allowed": len(errors) == 0,
                        "reason_codes": [],
                        "obligations": [],
                        "proposal_id": "",
                    },
                    "errors": errors,
                },
            )
        raise AssertionError(f"unexpected request path: {path}")

    transport = httpx.MockTransport(_response_for)
    http = HttpClient(base_url="http://brain-core", transport=transport)
    client = BrainClient(
        config=BrainSdkConfig(source="assistant", principal="operator"),
        http=http,
    )
    settings = SimpleNamespace(
        agent=SimpleNamespace(
            session_start_mode="existing",
            personality="default",
            operator_profile="Refer to me as 'boss'",
            system_prompt_append="",
            source="assistant",
            principal="operator",
            op_discovery_deny_list=(),
            tool_return_compress_threshold=4000,
            tool_return_max_chars=8000,
            tool_loop_tier2_hop_threshold=3,
        )
    )
    core_settings = SimpleNamespace(
        profile=SimpleNamespace(
            personality="default",
            operator=SimpleNamespace(profile_context="Refer to me as 'boss'"),
            system_prompt_append="",
        ),
    )
    runtime = operator_runtime.create_runtime(
        client=client,
        settings=cast(ActorSettings, settings),
        core_settings=cast(CoreSettings, core_settings),
    )
    response_text = asyncio.run(
        operator_runtime.process_instruction(
            runtime=runtime,
            instruction=scenario.instruction,
        )
    )
    client.close()
    return AgentTurnRunResult(response_text=response_text, calls=tuple(calls))


def _decode_request_json(request: httpx.Request) -> dict[str, Any]:
    """Decode one mock transport request body into a JSON object."""
    content = request.content.decode("utf-8").strip()
    if content == "":
        return {}
    decoded = json.loads(content)
    return decoded if isinstance(decoded, dict) else {}


def _json_response(
    request: httpx.Request,
    payload: dict[str, Any],
    *,
    status_code: int = 200,
) -> httpx.Response:
    """Return one JSON response bound to the initiating request."""
    return httpx.Response(status_code, json=payload, request=request)
