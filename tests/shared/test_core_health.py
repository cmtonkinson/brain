"""Unit tests for core aggregate health evaluation."""

from __future__ import annotations

import time
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from packages.brain_core import health as health_module
from packages.brain_shared.config import (
    CoreHealthSettings,
    CoreRuntimeSettings,
    CoreSettings,
    ResourcesSettings,
)
from packages.brain_shared.envelope import EnvelopeMeta, failure, new_meta, success
from packages.brain_shared.envelope.meta import EnvelopeKind
from packages.brain_shared.errors import dependency_error


class _HealthPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    detail: str = "ok"


@dataclass(frozen=True)
class _Manifest:
    id: str
    owner_service_id: str | None = None


class _Registry:
    def __init__(self) -> None:
        self._services = (_Manifest(id="service_a"), _Manifest(id="service_b"))
        self._resources = (_Manifest(id="substrate_postgres", owner_service_id=None),)

    def list_services(self) -> tuple[_Manifest, ...]:
        return self._services

    def list_resources(self) -> tuple[_Manifest, ...]:
        return self._resources


class _HealthyService:
    def health(self, *, meta: EnvelopeMeta):
        del meta
        return success(meta=_meta(), payload=_HealthPayload(service_ready=True))


class _FailingService:
    def health(self, *, meta: EnvelopeMeta):
        return failure(
            meta=meta,
            errors=[dependency_error("service down")],
        )


class _HealthyResource:
    def health(self) -> dict[str, object]:
        return {"ready": True, "detail": "ok"}


class _FailingResource:
    def health(self) -> dict[str, object]:
        return {"ready": False, "detail": "dependency down"}


def _meta() -> EnvelopeMeta:
    return new_meta(kind=EnvelopeKind.RESULT, source="test", principal="test")


def _settings(max_timeout_seconds: float = 1.0) -> CoreRuntimeSettings:
    """Build a minimal CoreRuntimeSettings for health evaluation tests."""
    return CoreRuntimeSettings(
        core=CoreSettings(
            health=CoreHealthSettings(max_timeout_seconds=max_timeout_seconds)
        ),
        resources=ResourcesSettings(),
    )


def test_evaluate_core_health_ready_when_services_and_postgres_are_ready(
    monkeypatch,
) -> None:
    monkeypatch.setattr(health_module, "get_registry", lambda: _Registry())

    result = health_module.evaluate_core_health(
        settings=_settings(),
        components={
            "service_a": _HealthyService(),
            "service_b": _HealthyService(),
            "substrate_postgres": _HealthyResource(),
        },
    )

    assert result.ready is True
    assert result.services["service_a"].ready is True
    assert result.services["service_b"].ready is True
    assert result.resources["substrate_postgres"].ready is True


def test_evaluate_core_health_degrades_when_any_service_fails(monkeypatch) -> None:
    monkeypatch.setattr(health_module, "get_registry", lambda: _Registry())

    result = health_module.evaluate_core_health(
        settings=_settings(),
        components={
            "service_a": _HealthyService(),
            "service_b": _FailingService(),
            "substrate_postgres": _HealthyResource(),
        },
    )

    assert result.ready is False
    assert result.services["service_b"].ready is False


def test_evaluate_core_health_degrades_when_shared_postgres_fails(monkeypatch) -> None:
    monkeypatch.setattr(health_module, "get_registry", lambda: _Registry())

    result = health_module.evaluate_core_health(
        settings=_settings(),
        components={
            "service_a": _HealthyService(),
            "service_b": _HealthyService(),
            "substrate_postgres": _FailingResource(),
        },
    )

    assert result.ready is False
    assert result.resources["substrate_postgres"].ready is False


def test_evaluate_core_health_timeout_marks_component_unhealthy(monkeypatch) -> None:
    monkeypatch.setattr(health_module, "get_registry", lambda: _Registry())

    class _SlowResource:
        def health(self) -> dict[str, object]:
            time.sleep(0.05)
            return {"ready": True, "detail": "ok"}

    result = health_module.evaluate_core_health(
        settings=_settings(max_timeout_seconds=0.01),
        components={
            "service_a": _HealthyService(),
            "service_b": _HealthyService(),
            "substrate_postgres": _SlowResource(),
        },
    )

    assert result.ready is False
    assert result.resources["substrate_postgres"].ready is False
    assert (
        "exceeded global max timeout" in result.resources["substrate_postgres"].detail
    )
