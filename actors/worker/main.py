"""Worker Actor: claims queued job executions and runs them via the Brain SDK."""

from __future__ import annotations

import os
import signal
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from lib.sdk.calls import JobClaimResult
from lib.sdk.client import BrainClient
from lib.sdk.config import BrainSdkConfig
from lib.sdk.errors import (
    BrainDependencyError,
    BrainDomainError,
    BrainTransportError,
)
from lib.shared.config.loader import load_actor_settings
from lib.shared.logging import configure_logging, get_logger

_LOGGER = get_logger(__name__)

_HEARTBEAT_FILE_ENV = "BRAIN_WORKER_HEARTBEAT_FILE"
_HEARTBEAT_PATH = Path("/run/brain/worker-heartbeat")
_WORKER_CHANNEL = "worker"

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
    value = os.getenv(_HEARTBEAT_FILE_ENV, "").strip()
    return Path(value) if value else _HEARTBEAT_PATH


def _write_heartbeat(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


# ---------------------------------------------------------------------------
# Per-thread client
# ---------------------------------------------------------------------------


def _get_thread_client(config: BrainSdkConfig) -> BrainClient:
    """Return the calling thread's dedicated BrainClient, creating it on first use."""
    if not hasattr(_thread_local, "client"):
        _thread_local.client = BrainClient(config=config)
    return _thread_local.client


# ---------------------------------------------------------------------------
# Execution runner (runs inside a pool thread)
# ---------------------------------------------------------------------------


def _run_execution(*, client: BrainClient, claim: JobClaimResult) -> None:
    """Execute one claimed job and report the result back to the Job Service."""
    execution_id = claim.execution_id
    _LOGGER.info(
        "Executing job: execution_id=%s capability_id=%s attempt=%d/%d",
        execution_id,
        claim.capability_id,
        claim.attempt_number,
        claim.max_attempts,
    )
    try:
        client.invoke_capability(
            capability_id=claim.capability_id,
            input_payload=claim.input_payload,
            actor=claim.actor,
            channel=_WORKER_CHANNEL,
            invocation_id=claim.trace_id,
            parent_invocation_id=claim.parent_envelope_id,
        )
        client.job_complete_execution(execution_id=execution_id)
        _LOGGER.info("Execution succeeded: execution_id=%s", execution_id)
    except BrainDependencyError as exc:
        _LOGGER.warning(
            "Execution failed (dependency, retryable): execution_id=%s error=%s",
            execution_id,
            exc,
        )
        _safe_fail(
            client=client,
            execution_id=execution_id,
            error_message=str(exc),
            is_retryable=True,
        )
    except BrainDomainError as exc:
        _LOGGER.warning(
            "Execution failed (domain): execution_id=%s error=%s",
            execution_id,
            exc,
        )
        _safe_fail(
            client=client,
            execution_id=execution_id,
            error_message=str(exc),
            is_retryable=False,
        )
    except BrainTransportError as exc:
        _LOGGER.warning(
            "Execution failed (transport, retryable): execution_id=%s error=%s",
            execution_id,
            exc,
        )
        _safe_fail(
            client=client,
            execution_id=execution_id,
            error_message=str(exc),
            is_retryable=exc.retryable,
        )
    except Exception as exc:  # noqa: BLE001
        _LOGGER.exception(
            "Execution failed (unexpected): execution_id=%s", execution_id
        )
        _safe_fail(
            client=client,
            execution_id=execution_id,
            error_message=f"unexpected error: {type(exc).__name__}: {exc}",
            is_retryable=False,
        )


def _safe_fail(
    *,
    client: BrainClient,
    execution_id: str,
    error_message: str,
    is_retryable: bool,
) -> None:
    """Report a failure result, swallowing any secondary transport errors."""
    try:
        client.job_fail_execution(
            execution_id=execution_id,
            error_message=error_message,
            is_retryable=is_retryable,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "Failed to report execution failure: execution_id=%s", execution_id
        )


def _dispatch(*, config: BrainSdkConfig, claim: JobClaimResult) -> None:
    """Resolve the calling thread's BrainClient and execute one claimed job.

    This is the function submitted to the ThreadPoolExecutor. It owns the
    thread-local client lifecycle so that _run_execution remains injectable
    and testable without a live SDK connection.
    """
    client = _get_thread_client(config)
    _run_execution(client=client, claim=claim)


# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------


def _main() -> None:
    settings = load_actor_settings()

    configure_logging(
        level=str(settings.logging.level),
        file_capture_enabled=settings.logging.file_capture_enabled,
        file_capture_level=str(settings.logging.file_capture_level),
        file_capture_directory=settings.logging.file_capture_directory,
        json_output=bool(settings.logging.json_output),
        process_name=str(settings.logging.process_name),
        environment=str(settings.logging.environment),
    )

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    worker_cfg = settings.worker
    max_workers: int = worker_cfg.max_workers
    poll_interval: float = worker_cfg.poll_interval_seconds

    sdk_config = BrainSdkConfig(
        host=settings.core.host,
        port=settings.core.port,
        timeout_seconds=settings.core.timeout_seconds,
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
                    _SHUTDOWN_EVENT.wait(timeout=0.25)
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
                    "Dispatching execution to pool: execution_id=%s capability_id=%s",
                    claim.execution_id,
                    claim.capability_id,
                )
                future: Future[None] = pool.submit(
                    _dispatch, config=sdk_config, claim=claim
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
