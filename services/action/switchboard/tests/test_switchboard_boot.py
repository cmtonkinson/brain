"""Tests for Switchboard boot hook callback registration behavior."""

from __future__ import annotations

from dataclasses import dataclass

from packages.brain_core.boot import BootContext
from packages.brain_shared.config import (
    CoreRuntimeSettings,
    CoreSettings,
    ResourcesSettings,
)
from packages.brain_shared.envelope import EnvelopeKind, failure, new_meta, success
from packages.brain_shared.errors import dependency_error
from services.action.switchboard.boot import (
    boot as run_boot,
    register_switchboard_callback_on_boot,
)
from services.action.switchboard.config import SwitchboardServiceSettings
from services.action.switchboard.domain import (
    HealthStatus,
    RegisterSignalCallbackResult,
)
from services.action.switchboard.service import SwitchboardService


@dataclass(frozen=True)
class _RegisterCall:
    registered: bool


class _FakeSwitchboardService(SwitchboardService):
    """Switchboard fake supporting programmable health readiness transitions."""

    def __init__(self) -> None:
        self.register_calls: list[_RegisterCall] = []
        self.health_calls = 0
        self.ready_after = 0
        self.register_ok = True

    def ingest_signal_message(
        self,
        *,
        meta,
        raw_body_json: str,
    ):
        del meta, raw_body_json
        raise NotImplementedError

    def register_signal_callback(self, *, meta):
        del meta
        self.register_calls.append(_RegisterCall(registered=True))
        if not self.register_ok:
            return failure(
                meta=_meta(),
                errors=[dependency_error("signal unavailable")],
            )
        return success(
            meta=_meta(),
            payload=RegisterSignalCallbackResult(
                registered=True,
                detail="registered",
            ),
        )

    def poll_operator_instruction(self, *, meta, wait_timeout_seconds: float = 0.0):
        del meta, wait_timeout_seconds
        raise NotImplementedError

    def health(self, *, meta):
        del meta
        self.health_calls += 1
        ready = self.health_calls > self.ready_after
        return success(
            meta=_meta(),
            payload=HealthStatus(
                service_ready=ready,
                adapter_ready=ready,
                cas_ready=ready,
                detail="ok" if ready else "warming",
            ),
        )


def _meta():
    """Build valid envelope metadata for test fakes."""
    return new_meta(kind=EnvelopeKind.RESULT, source="test", principal="switchboard")


def test_register_switchboard_callback_waits_for_health_and_registers() -> None:
    """Boot hook should wait for dependency readiness before registration."""
    service = _FakeSwitchboardService()
    service.ready_after = 2
    settings = SwitchboardServiceSettings(
        callback_register_max_retries=3,
        callback_register_retry_delay_seconds=0.001,
    )

    result = register_switchboard_callback_on_boot(service=service, settings=settings)

    assert result.ok is True
    assert service.health_calls == 3
    assert len(service.register_calls) == 1


def test_register_switchboard_callback_returns_dependency_error_when_not_ready() -> (
    None
):
    """Boot hook should fail when dependencies never become healthy."""
    service = _FakeSwitchboardService()
    service.ready_after = 99
    settings = SwitchboardServiceSettings(
        callback_register_max_retries=1,
        callback_register_retry_delay_seconds=0.001,
    )

    result = register_switchboard_callback_on_boot(service=service, settings=settings)

    assert result.ok is False
    assert result.errors[0].category.value == "dependency"
    assert len(service.register_calls) == 0


def test_boot_registers_signal_callback_once_ready() -> None:
    """Switchboard boot should register the Signal callback once dependencies are ready."""
    service = _FakeSwitchboardService()
    ctx = BootContext(
        settings=CoreRuntimeSettings(
            core=CoreSettings(), resources=ResourcesSettings()
        ),
        resolve_component=lambda component_id: (
            service if component_id == "service_switchboard" else None
        ),
    )

    run_boot(ctx)

    assert len(service.register_calls) == 1
