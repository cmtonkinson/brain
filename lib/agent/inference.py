"""Pure conversion helpers between the SDK chat surface and canonical IR."""

from __future__ import annotations

import json
from collections.abc import Iterable

from lib.sdk.calls import LmsChatToolCall


_NORMALIZED_FINISH_REASONS: frozenset[str] = frozenset(
    {"stop", "length", "content_filter", "tool_call", "error"}
)


def decode_tool_args_json(value: str) -> str | dict[str, object]:
    """Decode canonical tool args JSON into dict form when valid.

    Returns the raw string when the JSON is unparseable or top-level is
    not a dict; this matches the behaviour the upstream PydanticAI tool
    pipeline expects when passing through opaque-but-stringly args.
    """
    if value == "":
        return value
    try:
        payload = json.loads(value)
    except ValueError:
        return value
    if isinstance(payload, dict):
        return payload
    return value


def normalize_finish_reason(value: str) -> str | None:
    """Project provider-reported finish reasons into the supported subset."""
    if value in _NORMALIZED_FINISH_REASONS:
        return value
    return None


def partition_returned_tool_calls(
    *,
    tool_calls: tuple[LmsChatToolCall, ...],
    advertised_tool_names: Iterable[str],
) -> tuple[tuple[LmsChatToolCall, ...], tuple[str, ...]]:
    """Split returned tool calls into advertised-valid and invalid subsets.

    Accepts an iterable of advertised names rather than a typed
    ``ToolDefinition`` list so callers that build their tool advertisement
    set manually (e.g. the headless loop using SDK ``OpDescriptor``) can
    use the same partition without depending on PydanticAI types.
    """
    advertised = frozenset(advertised_tool_names)
    valid = tuple(item for item in tool_calls if item.tool_name in advertised)
    invalid = tuple(
        sorted(
            {item.tool_name for item in tool_calls if item.tool_name not in advertised}
        )
    )
    return valid, invalid


__all__ = [
    "decode_tool_args_json",
    "normalize_finish_reason",
    "partition_returned_tool_calls",
]
