"""Reusable in-process harness for one Brain Agent turn over mock Core HTTP."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from typing import Any

import httpx

from actors.agent import main as agent_main
from packages.brain_sdk import (
    BrainClient,
    BrainSdkConfig,
    CapabilityDescriptor,
    LmsChatResult,
    MemoryContextBlock,
    MemoryDialogueTurn,
    MemoryProfileContext,
    SwitchboardOperatorInstruction,
)
from packages.brain_shared.http.client import HttpClient
from packages.brain_shared.ids import generate_ulid_str


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
    capabilities: tuple[CapabilityDescriptor, ...] = ()
    instruction: SwitchboardOperatorInstruction = field(
        default_factory=lambda: SwitchboardOperatorInstruction(
            sender_e164="+12025550100",
            message_text="hello",
            timestamp_ms=1,
            source_device="1",
            source="signal",
            group_id=None,
            quote_target_timestamp_ms=None,
            reaction_target_timestamp_ms=None,
        )
    )
    context: MemoryContextBlock = field(
        default_factory=lambda: MemoryContextBlock(
            profile=MemoryProfileContext(
                operator_name="Operator",
                brain_name="Brain",
                brain_verbosity="normal",
            ),
            focus="current focus",
            dialogue=(
                MemoryDialogueTurn(
                    role="user",
                    content="hello",
                    is_summary=False,
                ),
            ),
            reference_snippets=(),
        )
    )
    chat_result: LmsChatResult = field(
        default_factory=lambda: LmsChatResult(
            text='{"kind":"final","content":"assistant reply"}',
            provider="unit",
            model="test-model",
        )
    )
    capability_invoke_output: dict[str, Any] | None = field(
        default_factory=lambda: {"decision": "sent"}
    )
    capability_invoke_errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AgentTurnRunResult:
    """Captured outcome for one agent turn harness execution."""

    response_text: str
    calls: tuple[MockCoreCall, ...]


def run_agent_turn_scenario(scenario: AgentTurnScenario) -> AgentTurnRunResult:
    """Run one full agent turn against a mock Core HTTP transport."""
    calls: list[MockCoreCall] = []

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
        if path == "/memory/get_latest_or_create_session":
            return _json_response(
                request,
                {
                    "session_id": scenario.session_id,
                    "errors": [],
                },
            )
        if path == "/capabilities/describe":
            return _json_response(
                request,
                {
                    "capabilities": [
                        {
                            "capability_id": item.capability_id,
                            "kind": item.kind,
                            "version": item.version,
                            "summary": item.summary,
                            "input_schema": item.input_schema,
                            "output_schema": item.output_schema,
                            "autonomy": item.autonomy,
                            "requires_approval": item.requires_approval,
                            "side_effects": list(item.side_effects),
                            "required_capabilities": list(item.required_capabilities),
                        }
                        for item in scenario.capabilities
                    ],
                    "errors": [],
                },
            )
        if path == "/memory/assemble_context":
            return _json_response(
                request,
                {
                    "payload": {
                        "profile": {
                            "operator_name": scenario.context.profile.operator_name,
                            "brain_name": scenario.context.profile.brain_name,
                            "brain_verbosity": scenario.context.profile.brain_verbosity,
                        },
                        "focus": scenario.context.focus,
                        "dialogue": [
                            {
                                "role": turn.role,
                                "content": turn.content,
                                "is_summary": turn.is_summary,
                            }
                            for turn in scenario.context.dialogue
                        ],
                        "reference_snippets": list(scenario.context.reference_snippets),
                    },
                    "errors": [],
                },
            )
        if path == "/lms/chat":
            return _json_response(
                request,
                {
                    "payload": {
                        "text": scenario.chat_result.text,
                        "provider": scenario.chat_result.provider,
                        "model": scenario.chat_result.model,
                    },
                    "errors": [],
                },
            )
        if path == "/memory/record_response":
            return _json_response(request, {"payload": True, "errors": []})
        if path == "/capabilities/invoke":
            return _json_response(
                request,
                {
                    "output_json": (
                        ""
                        if scenario.capability_invoke_output is None
                        else json.dumps(scenario.capability_invoke_output)
                    ),
                    "policy": {
                        "decision_id": generate_ulid_str(),
                        "allowed": len(scenario.capability_invoke_errors) == 0,
                        "reason_codes": [],
                        "obligations": [],
                        "proposal_id": "",
                    },
                    "errors": scenario.capability_invoke_errors,
                },
            )
        raise AssertionError(f"unexpected request path: {path}")

    transport = httpx.MockTransport(_response_for)
    http = HttpClient(base_url="http://brain-core", transport=transport)
    client = BrainClient(
        config=BrainSdkConfig(source="agent", principal="operator"),
        http=http,
    )
    runtime = agent_main._create_runtime(client=client)
    response_text = asyncio.run(
        agent_main._process_instruction(
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
