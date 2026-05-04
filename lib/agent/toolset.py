"""``BrainToolset`` — dynamic, filter-based tool visibility for agent runtimes.

Wraps all registered op tools and (optionally) the ``search_tools`` /
``get_tool_info`` discovery tools inside a PydanticAI ``FilteredToolset``
whose filter function re-evaluates on every hop against
``turn_state.active_tool_names``.

Tool visibility is controlled entirely by the turn state:

* ``active_tool_names`` is a monotonically growing ``set[str]`` within a
  turn — tools are added via ``get_tool_info`` but never removed.
* ``denied_op_ids`` prevents specific ops from being discovered or
  activated.
* Between turns, ``turn_state.reset_active_tools()`` resets to the
  always-on set plus carry-forward from the prior turn.

There is **no freeze mechanic**. The ``FilteredToolset`` re-evaluates on
every PydanticAI step, and the ``ToolManager`` is rebuilt from scratch
each step — so a tool activated by ``get_tool_info`` on hop N is
immediately dispatchable on hop N+1.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import FunctionToolset, Tool
from pydantic_ai.tools import RunContext, ToolDefinition

from lib.agent.tool_model import call_with_optional_meta
from lib.agent.tools import OpInvocationContext, build_op_tools
from lib.agent.turn_state import (
    GET_TOOL_INFO_TOOL_NAME,
    SEARCH_TOOLS_TOOL_NAME,
    TurnState,
)
from lib.sdk.calls import OpDescriptor
from lib.sdk.errors import BrainSdkError
from lib.shared.logging import get_logger

_LOGGER = get_logger(__name__)


def build_brain_toolset(
    *,
    client: object,
    descriptors: tuple[OpDescriptor, ...],
    turn_state: TurnState,
    invocation_context: OpInvocationContext | None = None,
    extra_input_properties: dict[str, object] | None = None,
    on_before_dispatch: Any = None,
    parent_invocation_id: str | None = None,
    include_discovery_tools: bool = True,
) -> FunctionToolset[None]:
    """Build one ``FunctionToolset`` containing all op and discovery tools.

    The returned toolset is intended to be wrapped in a
    ``FilteredToolset`` via :func:`filtered_brain_toolset` so that only
    tools in ``turn_state.active_tool_names`` are visible to the model.
    Callers who want all tools always visible (headless subagent) can use
    the ``FunctionToolset`` directly without filtering.
    """
    op_tools = build_op_tools(
        client=client,
        descriptors=descriptors,
        actor=turn_state.actor,
        channel=turn_state.channel,
        parent_invocation_id=parent_invocation_id,
        on_before_dispatch=on_before_dispatch,
        invocation_context=invocation_context,
        extra_input_properties=extra_input_properties,
    )
    all_tools: list[Tool[None]] = list(op_tools)
    if include_discovery_tools:
        all_tools.extend(
            _build_discovery_tools(
                client=client,
                turn_state=turn_state,
                extra_input_properties=extra_input_properties,
            )
        )
    return FunctionToolset(tools=all_tools)


def filtered_brain_toolset(
    *,
    client: object,
    descriptors: tuple[OpDescriptor, ...],
    turn_state: TurnState,
    invocation_context: OpInvocationContext | None = None,
    extra_input_properties: dict[str, object] | None = None,
    on_before_dispatch: Any = None,
    parent_invocation_id: str | None = None,
    include_discovery_tools: bool = True,
) -> Any:
    """Build a filtered toolset that shows only active tools per hop.

    Returns a ``FilteredToolset`` wrapping the full ``FunctionToolset``.
    The filter checks ``turn_state.active_tool_names`` on every hop.
    """
    base = build_brain_toolset(
        client=client,
        descriptors=descriptors,
        turn_state=turn_state,
        invocation_context=invocation_context,
        extra_input_properties=extra_input_properties,
        on_before_dispatch=on_before_dispatch,
        parent_invocation_id=parent_invocation_id,
        include_discovery_tools=include_discovery_tools,
    )

    def _filter(_ctx: RunContext[None], tool_def: ToolDefinition) -> bool:
        return tool_def.name in turn_state.active_tool_names

    return base.filtered(_filter)


# ---------------------------------------------------------------------------
# Discovery tools
# ---------------------------------------------------------------------------


def _build_discovery_tools(
    *,
    client: object,
    turn_state: TurnState,
    extra_input_properties: dict[str, object] | None = None,
) -> list[Tool[None]]:
    """Build ``search_tools`` and ``get_tool_info`` discovery tools."""
    extra_props = extra_input_properties or {}

    def _search_tools(
        query: str,
        limit: int | None = None,
        **_extra: Any,  # noqa: ARG001 — absorbs agent-context properties
    ) -> list[dict[str, object]]:
        results = call_with_optional_meta(
            client.search_ops,  # type: ignore[attr-defined]
            meta=turn_state.nested_call_meta(),
            query=query,
            limit=limit,
        )
        visible_results = [
            item for item in results if item.op_id not in turn_state.denied_op_ids
        ]
        return [
            {
                "tool_id": item.op_id,
                "required_params": list(item.required_params),
                "summary": item.summary,
            }
            for item in visible_results
        ]

    def _get_tool_info(
        tool_id: str,
        **_extra: Any,  # noqa: ARG001 — absorbs agent-context properties
    ) -> dict[str, object]:
        if tool_id in turn_state.denied_op_ids:
            return {
                "tool_id": tool_id,
                "available": False,
                "reason": "tool is not available to this agent",
            }
        try:
            descriptor = call_with_optional_meta(
                client.describe_op,  # type: ignore[attr-defined]
                meta=turn_state.nested_call_meta(),
                op_id=tool_id,
            )
        except BrainSdkError as exc:
            return {
                "tool_id": tool_id,
                "available": False,
                "reason": str(exc),
            }
        # Activate the tool so the FilteredToolset includes it on the
        # next hop. No freeze — active_tool_names is the sole authority.
        turn_state.active_tool_names.add(descriptor.op_id)
        return {
            "tool_id": descriptor.op_id,
            "available": True,
            "kind": descriptor.kind,
            "version": descriptor.version,
            "summary": descriptor.summary,
            "input_schema": descriptor.input_schema,
            "output_schema": descriptor.output_schema,
            "effect": descriptor.effect,
            "approval": descriptor.approval,
            "required_ops": list(descriptor.required_ops),
        }

    search_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
            **extra_props,
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    info_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "tool_id": {"type": "string"},
            **extra_props,
        },
        "required": ["tool_id"],
        "additionalProperties": False,
    }

    return [
        Tool.from_schema(
            _search_tools,
            name=SEARCH_TOOLS_TOOL_NAME,
            description="Search available tools by concept and return matches.",
            json_schema=search_schema,
        ),
        Tool.from_schema(
            _get_tool_info,
            name=GET_TOOL_INFO_TOOL_NAME,
            description=("Return the full schema and metadata for one tool by its ID."),
            json_schema=info_schema,
        ),
    ]


__all__ = [
    "build_brain_toolset",
    "filtered_brain_toolset",
]
