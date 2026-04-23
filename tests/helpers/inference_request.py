"""Reusable canonical inference-request builders for tests."""

from __future__ import annotations

from lib.shared.language_model import (
    InferenceCache,
    InferenceControls,
    InferenceCurrentTurn,
    InferenceEnvironmentContext,
    InferenceMemoryContext,
    InferenceMeta,
    InferenceOperatorMessage,
    InferenceParallelToolCalls,
    InferenceReferenceSnippet,
    InferenceRequest,
    InferenceSystem,
    InferenceSystemBlock,
    InferenceToolChoice,
    InferenceToolDefinition,
)


def make_inference_request(
    *,
    session_id: str = "session-1",
    conversation_episode_id: str = "episode-1",
    trace_id: str = "trace-1",
    source: str = "tests",
    principal: str = "operator",
    envelope_id: str = "env-1",
    parent_id: str = "",
    system_blocks: tuple[InferenceSystemBlock, ...] | None = None,
    memory_context: InferenceMemoryContext | None = None,
    environment_context: InferenceEnvironmentContext | None = None,
    operator_message: InferenceOperatorMessage | None = None,
    tools: tuple[InferenceToolDefinition, ...] = (),
    live_events: tuple[object, ...] = (),
    controls: InferenceControls | None = None,
    cache: InferenceCache | None = None,
) -> InferenceRequest:
    """Build one canonical inference request with test-friendly defaults."""
    return InferenceRequest(
        meta=InferenceMeta(
            trace_id=trace_id,
            session_id=session_id,
            conversation_episode_id=conversation_episode_id,
            source=source,
            principal=principal,
            envelope_id=envelope_id,
            parent_id=parent_id,
        ),
        system=InferenceSystem(
            blocks=(
                (
                    InferenceSystemBlock(
                        kind="assistant_persona",
                        text="You are Brain.",
                    ),
                )
                if system_blocks is None
                else system_blocks
            )
        ),
        memory_context=(
            InferenceMemoryContext(
                current_focus=None,
                recent_conversation_summary="",
                recent_turns=(),
                reference_snippets=(),
            )
            if memory_context is None
            else memory_context
        ),
        environment_context=(
            InferenceEnvironmentContext()
            if environment_context is None
            else environment_context
        ),
        current_turn=InferenceCurrentTurn(
            operator_message=(
                InferenceOperatorMessage(
                    channel="signal",
                    sender_e164="+12025550100",
                    message_text="hello",
                )
                if operator_message is None
                else operator_message
            )
        ),
        tools=tools,
        live_events=tuple(live_events),
        controls=(
            InferenceControls(
                allow_text_output=True,
                tool_choice=InferenceToolChoice(mode="auto"),
                parallel_tool_calls=InferenceParallelToolCalls(mode="allow"),
                profile="standard",
            )
            if controls is None
            else controls
        ),
        cache=InferenceCache(mode="none") if cache is None else cache,
    )


def make_reference_snippet(text: str) -> InferenceReferenceSnippet:
    """Return one canonical test reference snippet."""
    return InferenceReferenceSnippet(text=text)
