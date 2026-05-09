"""Subagent Actor: claims queued delegation invocations and runs them via the SDK."""

from __future__ import annotations

import signal
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from lib.agent import actor_process, subagent_runtime
from lib.sdk.calls import DelegationClaim
from lib.sdk.client import BrainClient
from lib.sdk.config import BrainSdkConfig
from lib.sdk.errors import (
    BrainDomainError,
    BrainTransportError,
)
from lib.shared.config.loader import load_actor_settings
from lib.shared.logging import get_logger

_LOGGER = get_logger(__name__)

_HEARTBEAT_FILE_ENV = "BRAIN_SUBAGENT_HEARTBEAT_FILE"
_HEARTBEAT_PATH = Path("/run/brain/subassistant-heartbeat")
# Saturation backpressure: how long to wait before re-checking the pool when all
# workers are busy. Shorter than poll_interval so a slot freeing up is noticed
# quickly without spinning.
_SATURATION_BACKOFF_SECONDS = 0.25

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
    return actor_process.resolve_env_path(
        env_var=_HEARTBEAT_FILE_ENV, default=_HEARTBEAT_PATH
    )


def _write_heartbeat(path: Path) -> None:
    """Touch the heartbeat file to indicate the actor poll loop is alive."""
    actor_process.touch_path(path)


# ---------------------------------------------------------------------------
# Loop dispatch (runs inside a pool thread)
# ---------------------------------------------------------------------------


def _dispatch(
    *,
    config: BrainSdkConfig,
    claim: DelegationClaim,
    approval_poll_interval_seconds: float,
    approval_poll_max_interval_seconds: float,
) -> None:
    """Run one claimed invocation under a fresh per-task BrainClient.

    Per-task clients ensure HTTP connection pools are released on completion
    even when the worker thread outlives the task.
    """
    with BrainClient(config=config) as client:
        subagent_runtime.run_invocation(
            client=client,
            claim=claim,
            approval_poll_interval_seconds=approval_poll_interval_seconds,
            approval_poll_max_interval_seconds=approval_poll_max_interval_seconds,
        )


# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------


def _main() -> None:
    settings = load_actor_settings()
    actor_process.configure_actor_logging(
        settings=settings,
        default_process_name="subagent",
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
    sdk_config = actor_process.sdk_config_from_parts(
        core_settings=settings.core,
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
                    approval_poll_interval_seconds=subagent_cfg.approval_poll_interval_seconds,
                    approval_poll_max_interval_seconds=subagent_cfg.approval_poll_max_interval_seconds,
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
