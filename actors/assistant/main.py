"""Runtime entrypoint for the long-lived Brain Assistant container."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

from lib.agent import actor_process, operator_runtime
from lib.sdk import BrainClient, BrainDomainError, BrainTransportError
from lib.shared.config import (
    ActorSettings,
    CoreRuntimeSettings,
    load_actor_settings,
    load_core_runtime_settings,
)
from lib.shared.observability import bootstrap_observability

_LOGGER = logging.getLogger(__name__)
_RUNNING = True
_LONG_POLL_BUFFER_SECONDS = 1.0
_MIN_LONG_POLL_SECONDS = 1.0
_TURN_FAILURE_BACKOFF_SECONDS = 1.0
_HEARTBEAT_FILE_ENV = "BRAIN_ASSISTANT_HEARTBEAT_FILE"
_HEARTBEAT_PATH = Path("/run/brain/assistant-heartbeat")


def _handle_shutdown(_signum: int, _frame: object) -> None:
    """Mark the agent runtime for graceful shutdown."""
    global _RUNNING
    _RUNNING = False


def _resolve_config_dir() -> Path | None:
    """Return an explicit Brain config directory when the env override is set."""
    value = os.getenv("BRAIN_CONFIG_DIR", "").strip()
    if value == "":
        return None
    return Path(value)


def _resolve_config_path() -> Path | None:
    """Return the explicit Brain config directory path."""
    return _resolve_config_dir()


def _resolve_core_config_path() -> Path | None:
    """Return the explicit Brain config directory path."""
    return _resolve_config_dir()


def _resolve_resources_config_path() -> Path | None:
    """Return the explicit Brain config directory path."""
    return _resolve_config_dir()


def _load_startup_settings() -> tuple[ActorSettings, CoreRuntimeSettings]:
    """Load actor and core settings using one optional config directory."""
    config_dir = _resolve_config_dir()
    settings = load_actor_settings(config_path=config_dir)
    core_runtime_settings = load_core_runtime_settings(core_config_path=config_dir)
    return settings, core_runtime_settings


def _resolve_heartbeat_path() -> Path:
    """Return the heartbeat file path used by container health checks."""
    return actor_process.resolve_env_path(
        env_var=_HEARTBEAT_FILE_ENV, default=_HEARTBEAT_PATH
    )


def _write_heartbeat(*, path: Path | None = None) -> None:
    """Touch the heartbeat file to indicate the agent event loop is alive."""
    heartbeat_path = _resolve_heartbeat_path() if path is None else path
    actor_process.touch_path(heartbeat_path)


def _configure_logging(*, settings: ActorSettings) -> None:
    """Install shared dual-path logging for the long-lived agent process."""
    actor_process.configure_actor_logging(
        settings=settings,
        default_process_name="assistant",
    )


def _long_poll_timeout_seconds(*, sdk_timeout_seconds: float) -> float:
    """Choose one bounded long-poll timeout that stays under the HTTP timeout."""
    return max(_MIN_LONG_POLL_SECONDS, sdk_timeout_seconds - _LONG_POLL_BUFFER_SECONDS)


async def _run_main() -> None:
    """Run the long-lived Brain Assistant process inside one event loop."""
    global _RUNNING
    _RUNNING = True

    settings, core_runtime_settings = _load_startup_settings()
    core_settings = core_runtime_settings.core
    _configure_logging(settings=settings)
    bootstrap_observability(
        settings=settings.observability,
        service_name=str(settings.logging.process_name),
        environment=str(settings.logging.environment),
    )
    heartbeat_path = _resolve_heartbeat_path()
    _write_heartbeat(path=heartbeat_path)

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    client = BrainClient(config=operator_runtime.sdk_config_from_settings(settings))
    try:
        runtime = operator_runtime.create_runtime(
            client=client,
            settings=settings,
            core_settings=core_settings,
            language_request_timeout_seconds=operator_runtime.derive_language_request_timeout_seconds(
                core_runtime_settings
            ),
        )
        _LOGGER.info(
            "brain assistant started",
            extra={
                "core_host": settings.core.host,
                "core_port": settings.core.port,
                "timeout_seconds": settings.core.timeout_seconds,
                "language_request_timeout_seconds": runtime.language_request_timeout_seconds,
                "source": settings.agent.source,
                "principal": settings.agent.principal,
                "session_id": runtime.session_id,
            },
        )
        wait_timeout_seconds = _long_poll_timeout_seconds(
            sdk_timeout_seconds=settings.core.timeout_seconds
        )
        while _RUNNING:
            try:
                _write_heartbeat(path=heartbeat_path)
                instruction = await asyncio.to_thread(
                    runtime.client.relay_poll_operator_instruction,
                    wait_timeout_seconds=wait_timeout_seconds,
                )
                _write_heartbeat(path=heartbeat_path)
                if instruction is None:
                    continue
                _LOGGER.debug(
                    "brain assistant received instruction",
                    extra={
                        "channel": instruction.source,
                        "sender_e164": instruction.sender_e164,
                        "message_text": instruction.message_text,
                    },
                )
                response_text = await operator_runtime.process_instruction(
                    runtime=runtime,
                    instruction=instruction,
                )
                _LOGGER.info(
                    "brain assistant completed turn",
                    extra={
                        "channel": instruction.source,
                        "sender_e164": instruction.sender_e164,
                        "response": response_text,
                    },
                )
                _write_heartbeat(path=heartbeat_path)
            except (BrainTransportError, BrainDomainError) as exc:
                _LOGGER.warning("brain assistant poll failed (will retry): %s", exc)
                _write_heartbeat(path=heartbeat_path)
                await asyncio.sleep(_TURN_FAILURE_BACKOFF_SECONDS)
            except Exception:
                _LOGGER.exception("brain assistant turn failed")
                _write_heartbeat(path=heartbeat_path)
                await asyncio.sleep(_TURN_FAILURE_BACKOFF_SECONDS)
    finally:
        client.close()
        _LOGGER.info("brain assistant stopped")


def main() -> None:
    """Run the long-lived Brain Assistant process."""
    asyncio.run(_run_main())


if __name__ == "__main__":
    main()
