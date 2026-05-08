"""Op-descriptor → PydanticAI ``Tool`` wrappers shared by all agent runtimes.

Every tool invocation flows through ``client.invoke_op`` and returns
structured error payloads for all SDK domain failure categories. The
optional ``OpInvocationContext`` callback layer adds trace propagation,
agent-context property stripping, and approval-gating awareness for
the operator-facing assistant; headless runtimes (subagent) omit it and
get the simpler direct-dispatch path with the same error handling.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic_ai import Tool

from lib.sdk.calls import OpDescriptor
from lib.sdk.errors import (
    BrainConflictError,
    BrainDependencyError,
    BrainDomainError,
    BrainInternalError,
    BrainNotFoundError,
    BrainPolicyError,
    BrainValidationError,
)
from lib.shared.logging import get_logger

_LOGGER = get_logger(__name__)


class OpInvocationContext(Protocol):
    """Optional callback surface for trace-aware, approval-gated op dispatch.

    When supplied, the tool builder delegates actor/channel resolution,
    trace metadata, proposal-token handling, and input-property stripping
    to the context object rather than using the static constructor args.
    """

    actor: str
    channel: str
    message_text: str

    def nested_call_meta(self) -> object | None:
        """Return metadata for one nested SDK call under the current model node."""

    def strip_input_payload(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Remove agent-only properties from the input before forwarding."""

    def proposal_token_for_retry(
        self, *, op_id: str, input_payload: dict[str, Any]
    ) -> tuple[str, str]:
        """Return (reply_token, reaction_token) for approval-retry matching."""

    def remember_pending_invocation(
        self,
        *,
        proposal_token: str,
        op_id: str,
        input_payload: dict[str, Any],
        approval: str,
        reason_codes: tuple[str, ...],
        expires_at: datetime | None,
    ) -> None:
        """Store one approval-gated invocation for future retry matching."""


def build_op_tools(
    *,
    client: object,
    descriptors: tuple[OpDescriptor, ...],
    actor: str = "",
    channel: str = "",
    parent_invocation_id: str | None = None,
    on_before_dispatch: Callable[[OpDescriptor], None] | None = None,
    invocation_context: OpInvocationContext | None = None,
    extra_input_properties: dict[str, object] | None = None,
) -> list[Tool[None]]:
    """Wrap each ``OpDescriptor`` in a PydanticAI ``Tool``.

    All invocations return structured error payloads for SDK domain
    failures.  When *invocation_context* is supplied, the dispatch path
    uses it for trace metadata, actor/channel resolution, input-property
    stripping, and approval-token accounting.  When omitted, the simpler
    headless dispatch path is used with the static *actor*/*channel* args.

    *extra_input_properties* (when non-empty) is merged into each tool's
    JSON schema ``properties`` so models can supply agent-level context
    fields alongside the op's own parameters.
    """
    return [
        _wrap_descriptor(
            client=client,
            descriptor=descriptor,
            actor=actor,
            channel=channel,
            parent_invocation_id=parent_invocation_id,
            on_before_dispatch=on_before_dispatch,
            invocation_context=invocation_context,
            extra_input_properties=extra_input_properties,
        )
        for descriptor in descriptors
    ]


# Keep the old name as an alias so existing callers don't break during
# migration; the headless loop and its tests can switch at their own pace.
build_op_tools_from_descriptors = build_op_tools


def op_error_payload(
    *,
    error: str,
    op_id: str,
    exc: BrainDomainError,
) -> dict[str, object]:
    """Return one stable tool error payload for SDK domain failures."""
    return {
        "error": error,
        "message": str(exc),
        "op_id": op_id,
        "details": [
            {
                "code": item.code,
                "message": item.message,
                "category": item.category,
                "retryable": item.retryable,
                "metadata": dict(item.metadata),
            }
            for item in exc.details
        ],
    }


def parse_optional_iso_datetime(value: object) -> datetime | None:
    """Parse one optional ISO-8601 datetime string, normalising to UTC."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized == "":
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _wrap_descriptor(
    *,
    client: object,
    descriptor: OpDescriptor,
    actor: str,
    channel: str,
    parent_invocation_id: str | None,
    on_before_dispatch: Callable[[OpDescriptor], None] | None,
    invocation_context: OpInvocationContext | None,
    extra_input_properties: dict[str, object] | None,
) -> Tool[None]:
    """Return one ``Tool[None]`` bound to ``client.invoke_op`` for one Op."""
    description = descriptor.summary.strip()
    input_schema = (
        {"type": "object", "properties": {}, "additionalProperties": False}
        if descriptor.input_schema is None
        else dict(descriptor.input_schema)
    )
    if extra_input_properties:
        props = dict(input_schema.get("properties", {}))
        props.update(extra_input_properties)
        input_schema = {**input_schema, "properties": props}

    op_id = descriptor.op_id
    approval = descriptor.approval

    if invocation_context is not None:
        invoke_fn = _make_context_invoke(
            client=client,
            op_id=op_id,
            approval=approval,
            ctx=invocation_context,
            on_before_dispatch=on_before_dispatch,
            descriptor=descriptor,
        )
    else:
        invoke_fn = _make_direct_invoke(
            client=client,
            op_id=op_id,
            actor=actor,
            channel=channel,
            parent_invocation_id=parent_invocation_id,
            on_before_dispatch=on_before_dispatch,
            descriptor=descriptor,
        )

    invoke_fn.__name__ = op_id
    invoke_fn.__doc__ = description or f"Invoke op {op_id}."

    return Tool.from_schema(
        invoke_fn,
        name=op_id,
        description=description,
        json_schema=input_schema,
    )


def _make_context_invoke(
    *,
    client: object,
    op_id: str,
    approval: str,
    ctx: OpInvocationContext,
    on_before_dispatch: Callable[[OpDescriptor], None] | None,
    descriptor: OpDescriptor,
) -> Callable[..., Any]:
    """Build an invoke closure with trace propagation and approval gating."""
    from lib.agent.tool_model import call_with_optional_meta

    def _invoke(**input_payload: Any) -> Any:
        if on_before_dispatch is not None:
            on_before_dispatch(descriptor)
        op_payload = ctx.strip_input_payload(dict(input_payload))
        reply_token, reaction_token = ctx.proposal_token_for_retry(
            op_id=op_id,
            input_payload=op_payload,
        )
        try:
            result = call_with_optional_meta(
                client.invoke_op,  # type: ignore[attr-defined]
                meta=ctx.nested_call_meta(),
                op_id=op_id,
                input_payload=op_payload,
                actor=ctx.actor,
                channel=ctx.channel,
                reply_to_proposal_token=reply_token,
                reaction_to_proposal_token=reaction_token,
                message_text=ctx.message_text,
            )
        except BrainPolicyError as exc:
            return _handle_policy_error(
                exc=exc,
                op_id=op_id,
                approval=approval,
                op_payload=op_payload,
                ctx=ctx,
            )
        except BrainValidationError as exc:
            return op_error_payload(error="validation_error", op_id=op_id, exc=exc)
        except BrainConflictError as exc:
            return op_error_payload(error="conflict_error", op_id=op_id, exc=exc)
        except BrainNotFoundError as exc:
            return op_error_payload(error="not_found", op_id=op_id, exc=exc)
        except BrainDependencyError as exc:
            return op_error_payload(error="dependency_error", op_id=op_id, exc=exc)
        except BrainInternalError as exc:
            _LOGGER.error("op tool internal error", extra={"op_id": op_id})
            return op_error_payload(error="internal_error", op_id=op_id, exc=exc)
        except BrainDomainError as exc:
            return op_error_payload(error="domain_error", op_id=op_id, exc=exc)
        return result.output

    return _invoke


def _make_direct_invoke(
    *,
    client: object,
    op_id: str,
    actor: str,
    channel: str,
    parent_invocation_id: str | None,
    on_before_dispatch: Callable[[OpDescriptor], None] | None,
    descriptor: OpDescriptor,
) -> Callable[..., Any]:
    """Build an invoke closure for headless runtimes (no approval gating)."""

    def _invoke(**input_payload: Any) -> Any:
        if on_before_dispatch is not None:
            on_before_dispatch(descriptor)
        try:
            result = client.invoke_op(  # type: ignore[attr-defined]
                op_id=op_id,
                input_payload=input_payload,
                actor=actor,
                channel=channel,
                parent_invocation_id=""
                if parent_invocation_id is None
                else parent_invocation_id,
            )
        except BrainValidationError as exc:
            return op_error_payload(error="validation_error", op_id=op_id, exc=exc)
        except BrainConflictError as exc:
            return op_error_payload(error="conflict_error", op_id=op_id, exc=exc)
        except BrainNotFoundError as exc:
            return op_error_payload(error="not_found", op_id=op_id, exc=exc)
        except BrainDependencyError as exc:
            return op_error_payload(error="dependency_error", op_id=op_id, exc=exc)
        except BrainInternalError as exc:
            _LOGGER.error("op tool internal error", extra={"op_id": op_id})
            return op_error_payload(error="internal_error", op_id=op_id, exc=exc)
        except BrainDomainError as exc:
            return op_error_payload(error="domain_error", op_id=op_id, exc=exc)
        return result.output

    return _invoke


def _handle_policy_error(
    *,
    exc: BrainPolicyError,
    op_id: str,
    approval: str,
    op_payload: dict[str, Any],
    ctx: OpInvocationContext,
) -> dict[str, object]:
    """Process one policy denial: store proposal token and return error payload."""
    metadata = {} if len(exc.details) == 0 else dict(exc.details[0].metadata)
    reason_codes = [
        item for item in metadata.get("reason_codes", "").split(",") if item != ""
    ]
    proposal_token = str(metadata.get("proposal_token", "")).strip()
    expires_at = parse_optional_iso_datetime(metadata.get("expires_at"))
    if proposal_token != "":
        ctx.remember_pending_invocation(
            proposal_token=proposal_token,
            op_id=op_id,
            input_payload=op_payload,
            approval=approval,
            reason_codes=tuple(reason_codes),
            expires_at=expires_at,
        )
    return {
        "error": "policy_denied",
        "message": str(exc),
        "op_id": op_id,
        "approval": approval,
        "proposal_token": proposal_token,
        "proposal_expires_at": ("" if expires_at is None else expires_at.isoformat()),
        "reason_codes": reason_codes,
    }


__all__ = [
    "OpInvocationContext",
    "build_op_tools",
    "build_op_tools_from_descriptors",
    "op_error_payload",
    "parse_optional_iso_datetime",
]
