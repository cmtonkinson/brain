"""Worker Actor: claims queued job executions and runs them via the Brain SDK."""

from __future__ import annotations

import signal
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from lib.agent import actor_process, worker_runtime
from lib.sdk.calls import JobClaimResult
from lib.sdk.client import BrainClient
from lib.sdk.config import BrainSdkConfig
from lib.sdk.errors import (
    BrainDomainError,
    BrainTransportError,
)
from lib.shared.config.loader import load_actor_settings
from lib.shared.logging import get_logger

_LOGGER = get_logger(__name__)

_HEARTBEAT_FILE_ENV = "BRAIN_WORKER_HEARTBEAT_FILE"
_HEARTBEAT_PATH = Path("/run/brain/worker-heartbeat")
# Saturation backpressure: how long to wait before re-checking the pool when all
# workers are busy. Shorter than poll_interval so a slot freeing up is noticed
# quickly without spinning.
_SATURATION_BACKOFF_SECONDS = 0.25

_RUNNING = True
_SHUTDOWN_EVENT = threading.Event()

# Thread-local storage so each pool thread owns its own HTTP client.
_thread_local = threading.local()


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------


def _handle_signal(sig: int, frame: object) -> None:  # noqa: ARG001
    global _RUNNING  # noqa: PLW0603
    _RUNNING = False
    _SHUTDOWN_EVENT.set()
    _LOGGER.info("Worker received signal %d — shutting down", sig)


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


def _resolve_heartbeat_path() -> Path:
    """Return the heartbeat file path used by container health checks."""
    return actor_process.resolve_env_path(
        env_var=_HEARTBEAT_FILE_ENV, default=_HEARTBEAT_PATH
    )


def _write_heartbeat(path: Path) -> None:
    actor_process.touch_path(path)


# ---------------------------------------------------------------------------
# Per-thread client
# ---------------------------------------------------------------------------


def _get_thread_client(config: BrainSdkConfig) -> BrainClient:
    """Return the calling thread's dedicated BrainClient, creating it on first use."""
    if not hasattr(_thread_local, "client"):
        _thread_local.client = BrainClient(config=config)
    return _thread_local.client


def _dispatch(*, config: BrainSdkConfig, claim: JobClaimResult, channel: str) -> None:
    """Resolve the calling thread's BrainClient and execute one claimed job."""
    client = _get_thread_client(config)
    worker_runtime.run_execution(client=client, claim=claim, channel=channel)


# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------


def _main() -> None:
    settings = load_actor_settings()
    actor_process.configure_actor_logging(
        settings=settings,
        default_process_name="worker",
    )

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    worker_cfg = settings.worker
    max_workers: int = worker_cfg.max_workers
    poll_interval: float = worker_cfg.poll_interval_seconds
    channel: str = worker_cfg.channel

    sdk_config = actor_process.sdk_config_from_parts(
        core_settings=settings.core,
        source=worker_cfg.source,
        principal=worker_cfg.principal,
    )

    heartbeat_path = _resolve_heartbeat_path()
    _LOGGER.info(
        "Worker starting: max_workers=%d poll_interval=%.1fs principal=%s source=%s",
        max_workers,
        poll_interval,
        worker_cfg.principal,
        worker_cfg.source,
    )

    pending: list[Future[None]] = []

    with ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="worker"
    ) as pool:
        # Main poll loop — single-threaded; only dispatch is parallelised.
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
                                "Worker thread raised uncaught exception: %s", exc
                            )
                pending = new_pending

                # Back off when pool is saturated.
                if len(pending) >= max_workers:
                    _SHUTDOWN_EVENT.wait(timeout=_SATURATION_BACKOFF_SECONDS)
                    continue

                # Claim next queued execution.
                try:
                    claim = main_client.job_claim_execution(worker_id=worker_cfg.source)
                except (BrainTransportError, BrainDomainError) as exc:
                    _LOGGER.warning("Claim failed (will retry): %s", exc)
                    _SHUTDOWN_EVENT.wait(timeout=poll_interval)
                    continue
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Unexpected claim error (will retry)")
                    _SHUTDOWN_EVENT.wait(timeout=poll_interval)
                    continue

                if claim is None:
                    # Nothing queued — sleep before next poll.
                    _SHUTDOWN_EVENT.wait(timeout=poll_interval)
                    continue

                _LOGGER.info(
                    "Dispatching execution to pool: execution_id=%s op_id=%s",
                    claim.execution_id,
                    claim.op_id,
                )
                future: Future[None] = pool.submit(
                    _dispatch, config=sdk_config, claim=claim, channel=channel
                )
                pending.append(future)

        finally:
            main_client.close()
            _LOGGER.info(
                "Worker shut down — waiting for %d in-flight jobs", len(pending)
            )

    _LOGGER.info("Worker exited cleanly")


if __name__ == "__main__":
    _main()
