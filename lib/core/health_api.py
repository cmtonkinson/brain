"""FastAPI route for Core aggregate health."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter

from lib.core.health import CoreHealthResult, evaluate_core_health
from lib.shared.config import CoreRuntimeSettings


def register_routes(
    *,
    router: APIRouter,
    settings: CoreRuntimeSettings,
    components: Mapping[str, object],
) -> None:
    """Register core health route on one router."""

    @router.get("/health", response_model=CoreHealthResult)
    def health() -> CoreHealthResult:
        return evaluate_core_health(settings=settings, components=components)
