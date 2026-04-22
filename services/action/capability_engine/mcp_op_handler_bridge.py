"""MCP Op handler bridge: builds CapabilityHandlers for MCP tool invocations."""

from __future__ import annotations

import json
import re
from typing import Any

from resources.adapters.mcp.adapter import McpAdapter, McpToolCallError
from services.action.capability_engine.domain import CapabilityExecutionResponse
from services.action.capability_engine.registry import (
    CapabilityHandler,
    CapabilityRuntime,
)
from services.action.policy_service.domain import CapabilityInvocationRequest

_MCP_CALL_TARGET_PREFIX = "mcp:"


def build_mcp_op_handler(
    *,
    server_id: str,
    tool_name: str,
    adapter: McpAdapter,
) -> CapabilityHandler:
    """Build a CapabilityHandler that delegates to an MCP tool via the adapter.

    The returned closure captures ``server_id``, ``tool_name``, and the
    adapter reference.  At invocation time it calls
    ``adapter.call_tool()`` and normalizes the MCP content result into a
    ``CapabilityExecutionResponse``.
    """

    def handler(
        request: CapabilityInvocationRequest,
        runtime: CapabilityRuntime,
    ) -> CapabilityExecutionResponse:
        result = adapter.call_tool(
            server_id=server_id,
            tool_name=tool_name,
            arguments=dict(request.input_payload),
        )
        if result.is_error:
            raise McpToolCallError(
                f"MCP tool error: server={server_id} tool={tool_name} "
                f"content={result.content}"
            )
        output = normalize_mcp_content(result.content)
        return CapabilityExecutionResponse(output=output)

    return handler


def parse_mcp_call_target(call_target: str) -> tuple[str, str]:
    """Parse ``mcp:<server_id>:<tool_name>`` into its parts.

    Raises ``ValueError`` when the format is invalid.
    """
    if not call_target.startswith(_MCP_CALL_TARGET_PREFIX):
        raise ValueError(f"not an MCP call_target: {call_target!r}")
    remainder = call_target[len(_MCP_CALL_TARGET_PREFIX) :]
    parts = remainder.split(":", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"invalid MCP call_target format: {call_target!r}")
    return parts[0], parts[1]


def is_mcp_call_target(call_target: str) -> bool:
    """Return True when call_target uses the ``mcp:`` prefix."""
    return call_target.startswith(_MCP_CALL_TARGET_PREFIX)


def mcp_capability_id(server_id: str, tool_name: str) -> str:
    """Derive a kebab-case capability_id from server_id and tool_name.

    Uses double-dash ``--`` as separator between server and tool to avoid
    ambiguity (MCP tool names may contain single hyphens or underscores).
    """
    server_part = re.sub(r"[^a-z0-9]+", "-", server_id.lower()).strip("-")
    tool_part = re.sub(r"[^a-z0-9]+", "-", tool_name.lower()).strip("-")
    return f"{server_part}--{tool_part}"


def normalize_mcp_content(content: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Normalize MCP tool content into a CES-compatible output dict.

    - Single text content: try JSON parse for structured output, fall back
      to ``{"text": "<raw>"}``.
    - Multiple content items or non-text: return ``{"content": [...]}``.
    - Empty content: return None.
    """
    if not content:
        return None
    text_items = [item for item in content if item.get("type") == "text"]
    if len(text_items) == 1 and len(content) == 1:
        raw_text = text_items[0].get("text", "")
        try:
            parsed = json.loads(raw_text)
        except Exception:  # noqa: BLE001
            parsed = None
        if isinstance(parsed, dict):
            return parsed
        return {"text": raw_text}
    return {"content": content}
