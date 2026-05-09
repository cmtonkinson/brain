"""Headless Subagent invocation runtime.

This module owns the per-invocation mechanics for claimed Delegation rows:
context-object resolution, cooperative cancellation hooks, running the shared
agent loop, and finalizing the invocation. The actor entrypoint owns only the
poll loop, signals, and container lifecycle.
"""

from __future__ import annotations

from typing import Callable

from lib.agent import (
    CancelDecision,
    CancelReason,
    CancellationError,
    LoopResult,
    TurnSummary,
    run as run_agent_loop,
)
from lib.sdk.calls import DelegationClaim
from lib.sdk.client import BrainClient
from lib.sdk.errors import BrainDependencyError, BrainDomainError, BrainTransportError
from lib.sdk.personality import render_system_prompt_blocks
from lib.shared.logging import get_logger

_LOGGER = get_logger(__name__)
_DEFAULT_INHERITED_CHANNEL = "agent"
_OBJECT_TEXT_KEYS = ("text", "content", "value", "result")


def assemble_context_text(*, client: BrainClient, claim: DelegationClaim) -> str | None:
    """Resolve object refs and concatenate them with inline context text."""
    parts: list[str] = []
    if claim.context_text is not None and claim.context_text.strip() != "":
        parts.append(claim.context_text)
    for object_ref in claim.context_object_refs:
        try:
            result = client.invoke_op(
                op_id="object-get-text",
                input_payload={"key": object_ref},
                actor=claim.principal,
                channel=resolve_inherited_channel(claim),
                parent_invocation_id=claim.invocation_id,
            )
        except (BrainTransportError, BrainDomainError) as exc:
            _LOGGER.warning(
                "subagent failed to resolve context object ref: invocation_id=%s ref=%s error=%s",
                claim.invocation_id,
                object_ref,
                exc,
            )
            continue
        text = coerce_object_text(result.output)
        if text != "":
            parts.append(f"<object ref={object_ref}>\n{text}\n</object>")
    if len(parts) == 0:
        return None
    return "\n\n".join(parts)


def resolve_inherited_channel(claim: DelegationClaim) -> str:
    """Return the channel string subagent calls should use."""
    candidate = claim.channel.strip()
    if candidate == "":
        return _DEFAULT_INHERITED_CHANNEL
    return candidate


def coerce_object_text(value: object) -> str:
    """Project the variable-shape object-get-text output into a plain string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in _OBJECT_TEXT_KEYS:
            inner = value.get(key)
            if isinstance(inner, str):
                return inner
    return ""


def build_cancel_check(
    *, client: BrainClient, invocation_id: str
) -> Callable[[], CancelDecision]:
    """Return a callable suitable for the shared agent loop cancel hook."""

    def _check() -> CancelDecision:
        try:
            view = client.delegation_status(invocation_id=invocation_id)
        except (BrainTransportError, BrainDomainError) as exc:
            _LOGGER.warning(
                "subagent status check failed; assuming continue: invocation_id=%s error=%s",
                invocation_id,
                exc,
            )
            return CancelDecision(should_stop=False, reason=None)
        if view.status in ("canceling", "canceled"):
            reason = (
                CancelReason(view.cancel_reason)
                if view.cancel_reason is not None
                else CancelReason.manual
            )
            return CancelDecision(should_stop=True, reason=reason)
        return CancelDecision(should_stop=False, reason=None)

    return _check


def build_record_turn(
    *, client: BrainClient, invocation_id: str
) -> Callable[[TurnSummary], CancelDecision]:
    """Return a callable suitable for the shared agent loop record hook."""

    def _record(_summary: TurnSummary) -> CancelDecision:
        try:
            decision = client.delegation_record_turn(invocation_id=invocation_id)
        except (BrainTransportError, BrainDomainError) as exc:
            _LOGGER.warning(
                "subagent record-turn failed; assuming continue: invocation_id=%s error=%s",
                invocation_id,
                exc,
            )
            return CancelDecision(should_stop=False, reason=None)
        if not decision.should_stop:
            return CancelDecision(should_stop=False, reason=None)
        reason = (
            CancelReason(decision.reason)
            if decision.reason is not None
            else CancelReason.budget_tokens
        )
        return CancelDecision(should_stop=True, reason=reason)

    return _record


def run_invocation(
    *,
    client: BrainClient,
    claim: DelegationClaim,
    approval_poll_interval_seconds: float = 2.0,
    approval_poll_max_interval_seconds: float = 5.0,
) -> None:
    """Execute one claimed Delegation invocation through the headless loop."""
    invocation_id = claim.invocation_id
    inherited_channel = resolve_inherited_channel(claim)
    inherited_principal = claim.principal

    _LOGGER.info(
        "subagent claimed invocation: invocation_id=%s personality=%s max_turns=%d "
        "channel=%s principal=%s",
        invocation_id,
        claim.personality_id,
        claim.max_turns,
        inherited_channel,
        inherited_principal,
    )

    try:
        system_blocks = render_system_prompt_blocks(personality=claim.personality_id)
    except Exception as exc:
        _LOGGER.exception(
            "subagent failed to render system blocks: invocation_id=%s personality=%s",
            invocation_id,
            claim.personality_id,
        )
        safe_finalize(
            client=client,
            invocation_id=invocation_id,
            status="failed",
            final_response=f"render_system_prompt_blocks: {type(exc).__name__}: {exc}",
        )
        return

    context_text = assemble_context_text(client=client, claim=claim)
    cancel_check = build_cancel_check(client=client, invocation_id=invocation_id)
    record_turn = build_record_turn(client=client, invocation_id=invocation_id)

    try:
        result: LoopResult = run_agent_loop(
            client=client,
            system_blocks=system_blocks,
            prompt=claim.prompt,
            context_text=context_text,
            principal=inherited_principal,
            source=inherited_principal,
            channel=inherited_channel,
            session_id="",
            parent_invocation_id=invocation_id,
            tool_allowlist=(
                None if claim.tool_allowlist is None else tuple(claim.tool_allowlist)
            ),
            max_turns=claim.max_turns,
            cancel_check=cancel_check,
            record_turn=record_turn,
            approval_poll_interval_seconds=approval_poll_interval_seconds,
            approval_poll_max_interval_seconds=approval_poll_max_interval_seconds,
        )
    except CancellationError as exc:
        _LOGGER.info(
            "subagent invocation canceled: invocation_id=%s reason=%s",
            invocation_id,
            exc.reason.value,
        )
        safe_finalize(
            client=client,
            invocation_id=invocation_id,
            status="canceled",
            cancel_reason=exc.reason.value,
        )
        return
    except BrainDependencyError as exc:
        _LOGGER.warning(
            "subagent invocation failed (dependency, retryable): invocation_id=%s error=%s",
            invocation_id,
            exc,
        )
        safe_finalize(
            client=client,
            invocation_id=invocation_id,
            status="failed",
            final_response=f"dependency: {exc}",
        )
        return
    except BrainDomainError as exc:
        _LOGGER.warning(
            "subagent invocation failed (domain): invocation_id=%s error=%s",
            invocation_id,
            exc,
        )
        safe_finalize(
            client=client,
            invocation_id=invocation_id,
            status="failed",
            final_response=f"domain: {exc}",
        )
        return
    except BrainTransportError as exc:
        _LOGGER.warning(
            "subagent invocation failed (transport): invocation_id=%s error=%s",
            invocation_id,
            exc,
        )
        safe_finalize(
            client=client,
            invocation_id=invocation_id,
            status="failed",
            final_response=f"transport: {exc}",
        )
        return
    except Exception as exc:
        _LOGGER.exception(
            "subagent invocation failed (unexpected): invocation_id=%s",
            invocation_id,
        )
        safe_finalize(
            client=client,
            invocation_id=invocation_id,
            status="failed",
            final_response=f"unexpected: {type(exc).__name__}: {exc}",
        )
        return

    safe_finalize(
        client=client,
        invocation_id=invocation_id,
        status="succeeded",
        final_response=result.final_response,
    )
    _LOGGER.info(
        "subagent invocation succeeded: invocation_id=%s turns=%d exhausted=%s",
        invocation_id,
        result.turn_count,
        result.exhausted,
    )


def safe_finalize(
    *,
    client: BrainClient,
    invocation_id: str,
    status: str,
    final_response: str | None = None,
    cancel_reason: str | None = None,
) -> None:
    """Finalize one invocation, swallowing secondary transport errors."""
    try:
        client.delegation_finalize_invocation(
            invocation_id=invocation_id,
            status=status,
            final_response=final_response,
            cancel_reason=cancel_reason,
        )
    except (BrainTransportError, BrainDomainError) as exc:
        _LOGGER.warning(
            "subagent finalize failed (transport): invocation_id=%s status=%s: %s",
            invocation_id,
            status,
            exc,
        )
    except Exception:
        _LOGGER.exception(
            "subagent finalize failed: invocation_id=%s status=%s",
            invocation_id,
            status,
        )


__all__ = [
    "assemble_context_text",
    "build_cancel_check",
    "build_record_turn",
    "coerce_object_text",
    "resolve_inherited_channel",
    "run_agent_loop",
    "run_invocation",
    "safe_finalize",
]
