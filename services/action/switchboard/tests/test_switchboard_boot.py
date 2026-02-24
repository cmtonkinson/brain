"""Tests for Switchboard boot hook callback registration behavior."""

from __future__ import annotations

from dataclasses import dataclass

from packages.brain_shared.envelope import EnvelopeKind, failure, new_meta, success
from packages.brain_shared.errors import dependency_error
from services.action.switchboard.boot import (
    build_switchboard_callback_url,
    register_switchboard_callback_on_boot,
)
from services.action.switchboard.config import SwitchboardServiceSettings
from services.action.switchboard.domain import HealthStatus, RegisterSignalWebhookResult
from services.action.switchboard.service import SwitchboardService


@dataclass(frozen=True)
class _RegisterCall:
    callback_url: str


class _FakeSwitchboardService(SwitchboardService):
    """Switchboard fake supporting programmable health readiness transitions."""

    def __init__(self) -> None:
        self.register_calls: list[_RegisterCall] = []
        self.health_calls = 0
        self.ready_after = 0
        self.register_ok = True

    def ingest_signal_webhook(
        self,
        *,
        meta,
        raw_body_json: str,
        header_timestamp: str,
        header_signature: str,
    ):
        del meta, raw_body_json, header_timestamp, header_signature
        raise NotImplementedError

    def register_signal_webhook(self, *, meta, callback_url: str):
        del meta
        self.register_calls.append(_RegisterCall(callback_url=callback_url))
        if not self.register_ok:
            return failure(
                meta=_meta(),
                errors=[dependency_error("signal unavailable")],
            )
        return success(
            meta=_meta(),
            payload=RegisterSignalWebhookResult(
                registered=True,
                callback_url=callback_url,
                detail="registered",
            ),
        )

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


def test_build_switchboard_callback_url_joins_base_and_path() -> None:
    """Callback URL should combine public base URL and canonical webhook path."""
    settings = SwitchboardServiceSettings(
        webhook_public_base_url="https://brain.example.com/api/",
        webhook_path="/hooks/signal",
    )

    callback_url = build_switchboard_callback_url(settings=settings)

    assert callback_url == "https://brain.example.com/api/hooks/signal"


def test_register_switchboard_callback_waits_for_health_and_registers() -> None:
    """Boot hook should wait for dependency readiness before registration."""
    service = _FakeSwitchboardService()
    service.ready_after = 2
    settings = SwitchboardServiceSettings(
        webhook_public_base_url="https://brain.example.com",
        webhook_path="/hooks/signal",
        webhook_register_max_retries=3,
        webhook_register_retry_delay_seconds=0.001,
    )

    result = register_switchboard_callback_on_boot(service=service, settings=settings)

    assert result.ok is True
    assert service.health_calls == 3
    assert [call.callback_url for call in service.register_calls] == [
        "https://brain.example.com/hooks/signal"
    ]


def test_register_switchboard_callback_returns_dependency_error_when_not_ready() -> (
    None
):
    """Boot hook should fail when dependencies never become healthy."""
    service = _FakeSwitchboardService()
    service.ready_after = 99
    settings = SwitchboardServiceSettings(
        webhook_register_max_retries=1,
        webhook_register_retry_delay_seconds=0.001,
    )

    result = register_switchboard_callback_on_boot(service=service, settings=settings)

    assert result.ok is False
    assert result.errors[0].category.value == "dependency"
    assert len(service.register_calls) == 0
