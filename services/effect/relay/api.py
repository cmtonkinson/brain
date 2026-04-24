"""FastAPI route registration for Relay Service.

Mounts inbound and outbound endpoints under one ``/relay/...`` prefix.
"""

from __future__ import annotations

from fastapi import APIRouter

from services.effect.relay._outbound.api import (
    register_routes as _register_outbound_routes,
)
from services.effect.relay._inbound.api import (
    register_routes as _register_inbound_routes,
)
from services.effect.relay.service import RelayService


def register_routes(*, router: APIRouter, service: RelayService) -> None:
    """Register all Relay HTTP routes on one router."""
    _register_inbound_routes(router=router, service=service)
    _register_outbound_routes(router=router, service=service)
