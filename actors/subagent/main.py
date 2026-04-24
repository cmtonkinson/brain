"""Subagent Actor: claims queued delegation invocations and runs them via the SDK."""

from __future__ import annotations

import os
import signal
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

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
from lib.sdk.config import BrainSdkConfig
from lib.sdk.errors import (
    BrainDependencyError,
    BrainDomainError,
    BrainTransportError,
)
from lib.sdk.personality import render_system_prompt_blocks
from lib.shared.config.loader import load_actor_settings
from lib.shared.logging import configure_logging, get_logger

_LOGGER = get_logger(__name__)

_HEARTBEAT_FILE_ENV = "BRAIN_SUBAGENT_HEARTBEAT_FILE"
_HEARTBEAT_PATH = Path("/run/brain/subassistant-heartbeat")
_DEFAULT_INHERITED_CHANNEL = "agent"
# Saturation backpressure: how long to wait before re-checking the pool when all
# workers are busy. Shorter than poll_interval so a slot freeing up is noticed
# quickly without spinning.
_SATURATION_BACKOFF_SECONDS = 0.25
# Candidate keys, in priority order, used to extract a string from an
# object-get-text dict response whose shape is not statically known.
_OBJECT_TEXT_KEYS = ("text", "content", "value", "result")

_RUNNING = True
_SHUTDOWN_EVENT = threading.Event()


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------


def _handle_signal(sig: int, frame: object) -> None:  # noqa: ARG001
    global _RUNNING  # noqa: PLW0603
    _RUNNING = False
    _SHUTDOWN_EVENT.set()
    _LOGGER.info("Subagent received signal %d — shutting down", sig)


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


def _resolve_heartbeat_path() -> Path:
    """Return the heartbeat file path used by container health checks."""
    value = os.getenv(_HEARTBEAT_FILE_ENV, "").strip()
    return Path(value) if value else _HEARTBEAT_PATH


def _write_heartbeat(path: Path) -> None:
    """Touch the heartbeat file to indicate the actor poll loop is alive."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


# ---------------------------------------------------------------------------
# Loop dispatch (runs inside a pool thread)
# ---------------------------------------------------------------------------


def _assemble_context_text(
    *,
    client: BrainClient,
    claim: DelegationClaim,
) -> str | None:
    """Resolve object refs and concatenate them with inline context text.

    Object resolution runs under the caller's inherited channel/principal so
    that policy applies the same gates the caller would have hit invoking
    ``object-get-text`` directly.
    """
    parts: list[str] = []
    if claim.context_text is not None and claim.context_text.strip() != "":
        parts.append(claim.context_text)
    for object_ref in claim.context_object_refs:
        try:
            result = client.invoke_op(
                op_id="object-get-text",
                input_payload={"key": object_ref},
                actor=claim.principal,
                channel=_resolve_inherited_channel(claim),
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
        text = _coerce_object_text(result.output)
        if text != "":
            parts.append(f"<object ref={object_ref}>\n{text}\n</object>")
    if len(parts) == 0:
        return None
    return "\n\n".join(parts)


def _resolve_inherited_channel(claim: DelegationClaim) -> str:
    """Return the channel string subagent calls should use.

    Mechanical inheritance from the row created by Delegation: when the
    caller's inferred channel is the empty string (rare, e.g. legacy clients
    that did not stamp a channel), default to ``agent`` so we do not invent
    a new restricted channel; the goal is for subagent tool calls to appear
    indistinguishable from the parent agent's own calls for policy purposes.
    """
    candidate = claim.channel.strip()
    if candidate == "":
        return _DEFAULT_INHERITED_CHANNEL
    return candidate


def _coerce_object_text(value: object) -> str:
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


def _build_cancel_check(
    *,
    client: BrainClient,
    invocation_id: str,
):
    """Return a callable suitable for the lib/agent loop's cancel_check hook."""

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


def _build_record_turn(
    *,
    client: BrainClient,
    invocation_id: str,
):
    """Return a callable suitable for the lib/agent loop's record_turn hook."""

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


def _run_invocation(
    *,
    client: BrainClient,
    claim: DelegationClaim,
) -> None:
    """Execute one claimed delegation invocation through the headless agent loop.

    Outbound tool calls are issued under the *inherited* principal/channel
    (recorded on the invocation row at queue time) so policy applies the
    same gates the caller would have hit invoking the tool directly. The
    Subagent Actor itself does not introduce a separate identity at this
    layer; it merely drives the loop.
    """
    invocation_id = claim.invocation_id
    inherited_channel = _resolve_inherited_channel(claim)
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
    except Exception as exc:  # noqa: BLE001
        _LOGGER.exception(
            "subagent failed to render system blocks: invocation_id=%s personality=%s",
            invocation_id,
            claim.personality_id,
        )
        _safe_finalize(
            client=client,
            invocation_id=invocation_id,
            status="failed",
            final_response=f"render_system_prompt_blocks: {type(exc).__name__}: {exc}",
        )
        return

    context_text = _assemble_context_text(client=client, claim=claim)

    cancel_check = _build_cancel_check(client=client, invocation_id=invocation_id)
    record_turn = _build_record_turn(client=client, invocation_id=invocation_id)

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
        )
    except CancellationError as exc:
        _LOGGER.info(
            "subagent invocation canceled: invocation_id=%s reason=%s",
            invocation_id,
            exc.reason.value,
        )
        _safe_finalize(
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
        _safe_finalize(
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
        _safe_finalize(
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
        _safe_finalize(
            client=client,
            invocation_id=invocation_id,
            status="failed",
            final_response=f"transport: {exc}",
        )
        return
    except Exception as exc:  # noqa: BLE001
        _LOGGER.exception(
            "subagent invocation failed (unexpected): invocation_id=%s",
            invocation_id,
        )
        _safe_finalize(
            client=client,
            invocation_id=invocation_id,
            status="failed",
            final_response=f"unexpected: {type(exc).__name__}: {exc}",
        )
        return

    _safe_finalize(
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


def _safe_finalize(
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
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "subagent finalize failed: invocation_id=%s status=%s",
            invocation_id,
            status,
        )


def _dispatch(
    *,
    config: BrainSdkConfig,
    claim: DelegationClaim,
) -> None:
    """Run one claimed invocation under a fresh per-task BrainClient.

    Per-task clients ensure HTTP connection pools are released on completion
    even when the worker thread outlives the task.
    """
    with BrainClient(config=config) as client:
        _run_invocation(client=client, claim=claim)


# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------


def _main() -> None:
    settings = load_actor_settings()
    process_name = settings.logging.process_name or "subagent"

    configure_logging(
        level=str(settings.logging.level),
        file_capture_enabled=settings.logging.file_capture_enabled,
        file_capture_level=str(settings.logging.file_capture_level),
        file_capture_directory=settings.logging.file_capture_directory,
        json_output=bool(settings.logging.json_output),
        process_name=process_name,
        environment=str(settings.logging.environment),
    )

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    subagent_cfg = settings.subagent
    max_workers: int = subagent_cfg.max_workers
    poll_interval: float = subagent_cfg.poll_interval_seconds

    # The actor's own SDK identity is used only for Delegation control-plane
    # calls (claim/finalize/record-turn). Outbound tool invocations within
    # the loop run under the *inherited* principal/channel recorded on the
    # invocation row, so policy treats them as if the original caller had
    # made the call directly.
    sdk_config = BrainSdkConfig(
        host=settings.core.host,
        port=settings.core.port,
        timeout_seconds=settings.core.timeout_seconds,
        source=subagent_cfg.source,
        principal=subagent_cfg.principal,
    )

    heartbeat_path = _resolve_heartbeat_path()
    _LOGGER.info(
        "subagent starting: max_workers=%d poll_interval=%.1fs source=%s",
        max_workers,
        poll_interval,
        subagent_cfg.source,
    )

    pending: list[Future[None]] = []

    with ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="subagent"
    ) as pool:
        main_client = BrainClient(config=sdk_config)
        try:
            while _RUNNING:
                _write_heartbeat(heartbeat_path)

                # Reap completed futures.
                new_pending: list[Future[None]] = []
                for f in pending:
                    if not f.done():
                        new_pending.append(f)
                    else:
                        exc = f.exception()
                        if exc is not None:
                            _LOGGER.error(
                                "subagent thread raised uncaught exception: %s", exc
                            )
                pending = new_pending

                # Back off when pool is saturated.
                if len(pending) >= max_workers:
                    _SHUTDOWN_EVENT.wait(timeout=_SATURATION_BACKOFF_SECONDS)
                    continue

                # Claim next queued invocation.
                try:
                    claim = main_client.delegation_claim_invocation(
                        claimed_by=subagent_cfg.source,
                    )
                except (BrainTransportError, BrainDomainError) as exc:
                    _LOGGER.warning("subagent claim failed (will retry): %s", exc)
                    _SHUTDOWN_EVENT.wait(timeout=poll_interval)
                    continue
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("subagent unexpected claim error (will retry)")
                    _SHUTDOWN_EVENT.wait(timeout=poll_interval)
                    continue

                if claim is None:
                    _SHUTDOWN_EVENT.wait(timeout=poll_interval)
                    continue

                _LOGGER.info(
                    "subagent dispatching invocation to pool: invocation_id=%s",
                    claim.invocation_id,
                )
                future: Future[None] = pool.submit(
                    _dispatch,
                    config=sdk_config,
                    claim=claim,
                )
                pending.append(future)

        finally:
            main_client.close()
            _LOGGER.info(
                "subagent shut down — waiting for %d in-flight invocation(s)",
                len(pending),
            )

    _LOGGER.info("subagent exited cleanly")


if __name__ == "__main__":
    _main()
