"""PydanticAI history processor: tool-return normalization and cache tiering.

Provides :func:`build_history_processor`, a factory that returns an async
``history_processor`` suitable for ``Agent(history_processors=[...])``.
The processor:

* **Tier 1 cache** — places a stable ``CachePoint`` after the initial
  system + Recall snapshot so it amortises across all intra-turn hops.
* **Tool-return normalization** — compresses oversized tool returns via a
  secondary LLM call (``language_chat`` quick profile) or truncates when
  compression fails or is inapplicable.
* **Tier 2 rolling cache** — conditionally inserts a second ``CachePoint``
  after accumulated tool exchanges when cost-benefit scoring justifies it.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic_ai.messages import (
    CachePoint,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserContent,
    UserPromptPart,
)
from pydantic_ai.tools import RunContext

from lib.agent.content_parts import (
    CachePointContentPart,
    content_has_cache_point,
    stringify_content,
    to_content_parts,
)
from lib.agent.inference_request import (
    classify_tool_result_status,
    is_not_found_tool_result,
    tool_args_json,
)
from lib.shared.logging import get_logger

_LOGGER = get_logger(__name__)

_PROMPT_TEMPLATE_VAR_RE = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")

# ---------------------------------------------------------------------------
# Rolling-cache scoring constants
# ---------------------------------------------------------------------------
ROLLING_CACHE_BASE_CONTINUATION_PROBABILITY = 0.20
ROLLING_CACHE_EXPLORE_WEIGHT = 0.35
ROLLING_CACHE_DISCOVERY_WEIGHT = 0.25
ROLLING_CACHE_FAILURE_WEIGHT = 0.20
ROLLING_CACHE_NOT_FOUND_WEIGHT = 0.10
ROLLING_CACHE_DECISIVE_SUCCESS_WEIGHT = -0.30
ROLLING_CACHE_HOP_DECAY = -0.03
ROLLING_CACHE_MIN_PROBABILITY = 0.05
ROLLING_CACHE_MAX_PROBABILITY = 0.95
ROLLING_CACHE_MAX_FUTURE_REUSES = 3

ANTHROPIC_CACHE_READ_SAVINGS_FACTOR = 0.90
ANTHROPIC_CACHE_WRITE_PREMIUM_FACTOR = 0.25


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompressedToolReturn:
    """Result of one secondary Language compression call for a tool return."""

    content: str
    model: str
    provider: str


@dataclass(frozen=True, slots=True)
class NormalizedToolReturn:
    """Display-safe tool return plus audit metadata for one tool execution."""

    content: str
    normalization_kind: str
    raw_content: str
    raw_char_count: int
    final_char_count: int
    compressed_by_model: str = ""
    compressed_by_provider: str = ""


# ---------------------------------------------------------------------------
# Prompt template rendering
# ---------------------------------------------------------------------------


def render_prompt_template(template: str, /, **values: str) -> str:
    """Render one ``{{ var }}`` template and reject unresolved placeholders."""

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ValueError(f"unresolved prompt template placeholder: {{{{{key}}}}}")
        return values[key]

    rendered = _PROMPT_TEMPLATE_VAR_RE.sub(_replace, template)
    unresolved = _PROMPT_TEMPLATE_VAR_RE.findall(rendered)
    if unresolved:
        raise ValueError(f"prompt template has unresolved placeholders: {unresolved}")
    return rendered


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def estimate_token_count(text: str) -> int:
    """Estimate token count with the same simple heuristic Recall uses internally."""
    words = len([item for item in text.split() if item])
    if words <= 0:
        return 0
    estimated = words * 3
    return (estimated + 1) // 2


def estimate_uncached_delta_tokens(
    messages: list[ModelRequest | ModelResponse],
) -> int:
    """Estimate token growth since the most recent explicit cachepoint."""
    segments: list[str] = []

    def append_text(text: str) -> None:
        normalized = text.strip()
        if normalized != "":
            segments.append(normalized)

    def reset_segments() -> None:
        segments.clear()

    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart):
                    for content_part in to_content_parts(part.content):
                        if isinstance(content_part, CachePointContentPart):
                            reset_segments()
                            continue
                        append_text(stringify_content(content_part))
                    continue
                if isinstance(part, ToolReturnPart):
                    append_text(part.tool_name)
                    append_text(stringify_content(part.content))
                    continue
                system_prompt = getattr(part, "content", None)
                if isinstance(system_prompt, str):
                    append_text(system_prompt)
            continue
        for part in message.parts:
            if isinstance(part, TextPart):
                append_text(part.content)
            elif isinstance(part, ToolCallPart):
                append_text(part.tool_name)
                append_text(tool_args_json(part.args))
    return estimate_token_count("\n".join(segments))


# ---------------------------------------------------------------------------
# Rolling-cache scoring
# ---------------------------------------------------------------------------


def rolling_cache_expected_reuses(
    *,
    tool_returns: list[ToolReturnPart],
    call_args_by_id: dict[str, dict[str, object]],
    hop_count: int,
    discovery_tool_names: frozenset[str] = frozenset(),
) -> float:
    """Estimate expected future compatible reuses for one rolling cachepoint."""
    if len(tool_returns) == 0:
        return 0.0
    total = float(len(tool_returns))
    explore_count = 0.0
    discovery_count = 0.0
    failure_count = 0.0
    not_found_count = 0.0
    decisive_success_count = 0.0

    for part in tool_returns:
        call_args = call_args_by_id.get(part.tool_call_id, {})
        call_mode = str(call_args.get("call_mode", "explore")).strip() or "explore"
        status = classify_tool_result_status(part.content)
        if call_mode == "explore":
            explore_count += 1.0
        if part.tool_name in discovery_tool_names:
            discovery_count += 1.0
        if status in {"error", "empty"}:
            failure_count += 1.0
        if is_not_found_tool_result(part.content):
            not_found_count += 1.0
        if call_mode == "decide" and status == "success":
            decisive_success_count += 1.0

    continuation_probability = ROLLING_CACHE_BASE_CONTINUATION_PROBABILITY
    continuation_probability += ROLLING_CACHE_EXPLORE_WEIGHT * (explore_count / total)
    continuation_probability += ROLLING_CACHE_DISCOVERY_WEIGHT * (
        discovery_count / total
    )
    continuation_probability += ROLLING_CACHE_FAILURE_WEIGHT * (failure_count / total)
    continuation_probability += ROLLING_CACHE_NOT_FOUND_WEIGHT * (
        not_found_count / total
    )
    continuation_probability += ROLLING_CACHE_DECISIVE_SUCCESS_WEIGHT * (
        decisive_success_count / total
    )
    continuation_probability += ROLLING_CACHE_HOP_DECAY * max(0.0, hop_count - 3.0)
    continuation_probability = max(
        ROLLING_CACHE_MIN_PROBABILITY,
        min(ROLLING_CACHE_MAX_PROBABILITY, continuation_probability),
    )

    expected_reuses = 0.0
    for power in range(1, ROLLING_CACHE_MAX_FUTURE_REUSES + 1):
        expected_reuses += continuation_probability**power
    return expected_reuses


def rolling_cachepoint_score(
    *,
    tool_returns: list[ToolReturnPart],
    call_args_by_id: dict[str, dict[str, object]],
    hop_count: int,
    candidate_messages: list[ModelRequest | ModelResponse],
    discovery_tool_names: frozenset[str] = frozenset(),
) -> float:
    """Return one concrete Anthropic price-weighted score for a rolling cachepoint."""
    delta_tokens = estimate_uncached_delta_tokens(candidate_messages)
    expected_reuses = rolling_cache_expected_reuses(
        tool_returns=tool_returns,
        call_args_by_id=call_args_by_id,
        hop_count=hop_count,
        discovery_tool_names=discovery_tool_names,
    )
    return float(delta_tokens) * (
        (ANTHROPIC_CACHE_READ_SAVINGS_FACTOR * expected_reuses)
        - ANTHROPIC_CACHE_WRITE_PREMIUM_FACTOR
    )


# ---------------------------------------------------------------------------
# Tool-return normalization
# ---------------------------------------------------------------------------


def log_tool_return_audit(
    *,
    tool_name: str,
    tool_call_id: str,
    tool_args: dict[str, object],
    normalized: NormalizedToolReturn,
) -> None:
    """Emit one structured audit record for a normalized tool return."""
    _LOGGER.debug(
        "normalized tool return",
        extra={
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "tool_input": tool_args,
            "raw_output": normalized.raw_content,
            "display_output": normalized.content,
            "normalization_kind": normalized.normalization_kind,
            "raw_char_count": normalized.raw_char_count,
            "final_char_count": normalized.final_char_count,
            "compressed_by_model": normalized.compressed_by_model,
            "compressed_by_provider": normalized.compressed_by_provider,
        },
    )


async def compress_tool_return(
    *,
    client: object,
    tool_name: str,
    call_mode: str,
    response_detail: str,
    raw_content: str,
    max_chars: int,
    compress_system_prompt: str,
    compress_user_template: str,
    timeout_seconds: float | None = None,
) -> CompressedToolReturn:
    """Call quick chat to compress one large tool return."""
    intent_hint = response_detail.strip() or f"tool call: {tool_name}"
    user_content = render_prompt_template(
        compress_user_template,
        tool_name=tool_name,
        call_mode=call_mode,
        intent=intent_hint,
        raw_output=raw_content[:max_chars],
    )
    try:
        result = await asyncio.to_thread(
            client.language_chat,  # type: ignore[attr-defined]
            system_prompt=compress_system_prompt,
            prompt=user_content,
            profile="quick",
            timeout_seconds=timeout_seconds,
        )
        compressed = result.text.strip()
        if compressed:
            return CompressedToolReturn(
                content=compressed,
                model=result.model,
                provider=result.provider,
            )
    except Exception:
        _LOGGER.warning(
            "tool return compression failed; using truncation",
            extra={"tool_name": tool_name},
        )
    return CompressedToolReturn(
        content=raw_content[:max_chars] + "\n[truncated]",
        model="",
        provider="",
    )


async def normalize_tool_return(
    *,
    client: object,
    timeout_seconds: float | None = None,
    tool_name: str,
    tool_call_id: str,
    tool_args: dict[str, object],
    raw_content: str,
    compress_threshold: int,
    max_chars: int,
    compress_system_prompt: str,
    compress_user_template: str,
) -> NormalizedToolReturn:
    """Normalize one tool return before it can re-enter the main model loop."""
    call_mode = str(tool_args.get("call_mode", "explore")).strip() or "explore"
    response_detail = str(tool_args.get("response_detail", ""))
    raw_char_count = len(raw_content)

    if raw_char_count <= compress_threshold:
        normalized = NormalizedToolReturn(
            content=raw_content,
            normalization_kind="pass_through",
            raw_content=raw_content,
            raw_char_count=raw_char_count,
            final_char_count=raw_char_count,
        )
        log_tool_return_audit(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args=tool_args,
            normalized=normalized,
        )
        return normalized

    if call_mode == "decide":
        compressed = await compress_tool_return(
            client=client,
            tool_name=tool_name,
            call_mode=call_mode,
            response_detail=response_detail,
            raw_content=raw_content,
            max_chars=max_chars,
            compress_system_prompt=compress_system_prompt,
            compress_user_template=compress_user_template,
            timeout_seconds=timeout_seconds,
        )
        normalized = NormalizedToolReturn(
            content=compressed.content,
            normalization_kind="compress",
            raw_content=raw_content,
            raw_char_count=raw_char_count,
            final_char_count=len(compressed.content),
            compressed_by_model=compressed.model,
            compressed_by_provider=compressed.provider,
        )
        log_tool_return_audit(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args=tool_args,
            normalized=normalized,
        )
        return normalized

    if raw_char_count > max_chars:
        truncated = raw_content[:max_chars] + "\n[truncated]"
        normalized = NormalizedToolReturn(
            content=truncated,
            normalization_kind="truncate",
            raw_content=raw_content,
            raw_char_count=raw_char_count,
            final_char_count=len(truncated),
        )
        log_tool_return_audit(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args=tool_args,
            normalized=normalized,
        )
        return normalized

    normalized = NormalizedToolReturn(
        content=raw_content,
        normalization_kind="pass_through",
        raw_content=raw_content,
        raw_char_count=raw_char_count,
        final_char_count=raw_char_count,
    )
    log_tool_return_audit(
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_args=tool_args,
        normalized=normalized,
    )
    return normalized


# ---------------------------------------------------------------------------
# History processor factory
# ---------------------------------------------------------------------------


def build_history_processor(
    *,
    client: object,
    timeout_seconds: float | None,
    compress_threshold: int,
    max_chars: int,
    tier2_hop_threshold: int,
    compress_system_prompt: str,
    compress_user_template: str,
    discovery_tool_names: frozenset[str] = frozenset(),
) -> Any:
    """Return a PydanticAI history_processor managing caching and tool-return size.

    Parameters are bound at construction time so the returned async function
    is a zero-argument closure suitable for ``Agent(history_processors=[...])``.
    """

    def _tool_call_args_index(
        msgs: list[ModelRequest | ModelResponse],
    ) -> dict[str, dict[str, object]]:
        index: dict[str, dict[str, object]] = {}
        for msg in msgs:
            if not isinstance(msg, ModelResponse):
                continue
            for part in msg.parts:
                if not isinstance(part, ToolCallPart):
                    continue
                try:
                    args = (
                        part.args
                        if isinstance(part.args, dict)
                        else json.loads(part.args or "{}")
                    )
                    if isinstance(args, dict):
                        index[part.tool_call_id] = args
                except ValueError, TypeError:
                    pass
        return index

    async def _process_history(
        _ctx: RunContext[None],
        messages: list[ModelRequest | ModelResponse],
    ) -> list[ModelRequest | ModelResponse]:
        result: list[ModelRequest | ModelResponse] = []
        tier1_placed = False
        hop_count = sum(1 for m in messages if isinstance(m, ModelResponse))
        call_args_by_id = _tool_call_args_index(messages)

        for i, message in enumerate(messages):
            if not isinstance(message, ModelRequest):
                result.append(message)
                continue

            new_parts: list[Any] = []
            for part in message.parts:
                if isinstance(part, UserPromptPart) and not tier1_placed:
                    if content_has_cache_point(part.content):
                        new_parts.append(part)
                    else:
                        if isinstance(part.content, str):
                            new_content: list[UserContent] = [part.content]
                        else:
                            new_content = list(part.content)
                        new_content.append(CachePoint())
                        new_parts.append(UserPromptPart(content=new_content))
                    tier1_placed = True
                    continue

                if isinstance(part, ToolReturnPart):
                    raw = stringify_content(part.content)
                    call_args = call_args_by_id.get(part.tool_call_id, {})
                    normalized = await normalize_tool_return(
                        client=client,
                        timeout_seconds=timeout_seconds,
                        tool_name=part.tool_name,
                        tool_call_id=part.tool_call_id,
                        tool_args=call_args,
                        raw_content=raw,
                        compress_threshold=compress_threshold,
                        max_chars=max_chars,
                        compress_system_prompt=compress_system_prompt,
                        compress_user_template=compress_user_template,
                    )
                    new_parts.append(
                        ToolReturnPart(
                            tool_name=part.tool_name,
                            content=normalized.content,
                            tool_call_id=part.tool_call_id,
                        )
                    )
                    continue

                new_parts.append(part)

            if (
                hop_count >= tier2_hop_threshold
                and i == len(messages) - 1
                and any(isinstance(p, ToolReturnPart) for p in new_parts)
            ):
                tool_returns = [
                    part for part in new_parts if isinstance(part, ToolReturnPart)
                ]
                last_tool_idx = max(
                    j for j, p in enumerate(new_parts) if isinstance(p, ToolReturnPart)
                )
                candidate_parts = list(new_parts)
                candidate_parts.insert(
                    last_tool_idx + 1,
                    UserPromptPart(content=[CachePoint()]),
                )
                score = rolling_cachepoint_score(
                    tool_returns=tool_returns,
                    call_args_by_id=call_args_by_id,
                    hop_count=hop_count,
                    candidate_messages=[
                        *result,
                        ModelRequest(parts=new_parts),
                    ],
                    discovery_tool_names=discovery_tool_names,
                )
                if score > 0.0:
                    new_parts = candidate_parts

            result.append(ModelRequest(parts=new_parts))

        return result

    return _process_history


__all__ = [
    "CompressedToolReturn",
    "NormalizedToolReturn",
    "build_history_processor",
    "compress_tool_return",
    "estimate_token_count",
    "estimate_uncached_delta_tokens",
    "log_tool_return_audit",
    "normalize_tool_return",
    "render_prompt_template",
    "rolling_cache_expected_reuses",
    "rolling_cachepoint_score",
]
