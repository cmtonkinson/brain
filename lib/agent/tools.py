"""Op-descriptor → PydanticAI ``Tool`` wrappers for headless agent runtimes.

Exposes the configured Op set as PydanticAI tools that call back into
``BrainClient.invoke_op``, without the approval gating, dynamic tool
exposure, or discovery-tool plumbing the operator-facing agent layers on
top.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic_ai import Tool

from lib.sdk.calls import OpDescriptor
from lib.sdk.client import BrainClient


def build_op_tools_from_descriptors(
    *,
    client: BrainClient,
    descriptors: tuple[OpDescriptor, ...],
    actor: str,
    channel: str,
    parent_invocation_id: str | None = None,
    on_before_dispatch: Callable[[OpDescriptor], None] | None = None,
) -> list[Tool[None]]:
    """Wrap each ``OpDescriptor`` in a PydanticAI ``Tool`` for the headless loop.

    ``on_before_dispatch`` runs (if supplied) before each tool invocation;
    headless callers use it to surface cooperative cancellation or budget
    checkpoints. The dispatch path itself is intentionally minimal: kwargs
    received from the model are forwarded verbatim as ``input_payload`` to
    ``client.invoke_op``, mirroring how the Subagent invocation row's
    inherited principal/channel govern policy gating.
    """
    tools: list[Tool[None]] = []
    for descriptor in descriptors:
        tool = _wrap_descriptor(
            client=client,
            descriptor=descriptor,
            actor=actor,
            channel=channel,
            parent_invocation_id=parent_invocation_id,
            on_before_dispatch=on_before_dispatch,
        )
        tools.append(tool)
    return tools


def _wrap_descriptor(
    *,
    client: BrainClient,
    descriptor: OpDescriptor,
    actor: str,
    channel: str,
    parent_invocation_id: str | None,
    on_before_dispatch: Callable[[OpDescriptor], None] | None,
) -> Tool[None]:
    """Return one ``Tool[None]`` bound to ``client.invoke_op`` for the given Op."""
    description = descriptor.summary.strip()
    input_schema = (
        {"type": "object", "properties": {}, "additionalProperties": False}
        if descriptor.input_schema is None
        else dict(descriptor.input_schema)
    )

    op_id = descriptor.op_id

    def _invoke(**input_payload: Any) -> Any:
        if on_before_dispatch is not None:
            on_before_dispatch(descriptor)
        result = client.invoke_op(
            op_id=op_id,
            input_payload=input_payload,
            actor=actor,
            channel=channel,
            parent_invocation_id=""
            if parent_invocation_id is None
            else parent_invocation_id,
        )
        return result.output

    _invoke.__name__ = op_id
    _invoke.__doc__ = description or f"Invoke op {op_id}."

    return Tool.from_schema(
        _invoke,
        name=op_id,
        description=description,
        json_schema=input_schema,
    )


__all__ = ["build_op_tools_from_descriptors"]
