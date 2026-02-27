"""FastAPI route for Core aggregate health."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter
from pydantic import BaseModel

from packages.brain_core.health import evaluate_core_health
from packages.brain_shared.config import CoreRuntimeSettings


class _ComponentStatus(BaseModel):
    ready: bool
    detail: str


class _HealthResponse(BaseModel):
    ready: bool
    services: dict[str, _ComponentStatus]
    resources: dict[str, _ComponentStatus]


def register_routes(
    *,
    router: APIRouter,
    settings: CoreRuntimeSettings,
    components: Mapping[str, object],
) -> None:
    """Register core health route on one router."""

    @router.get("/health", response_model=_HealthResponse)
    def health() -> _HealthResponse:
        result = evaluate_core_health(settings=settings, components=components)
        return _HealthResponse(
            ready=result.ready,
            services={
                k: _ComponentStatus(ready=v.ready, detail=v.detail)
                for k, v in result.services.items()
            },
            resources={
                k: _ComponentStatus(ready=v.ready, detail=v.detail)
                for k, v in result.resources.items()
            },
        )
