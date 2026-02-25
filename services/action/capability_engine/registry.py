"""Capability registry loading and handler wiring for Capability Engine."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import yaml

from services.action.capability_engine.domain import (
    CapabilityExecutionResponse,
    CapabilitySpec,
)
from services.action.policy_service.domain import CapabilityInvocationRequest


class CapabilityRuntime(Protocol):
    """Runtime helper contract exposed to capability handlers."""

    def invoke_nested(
        self,
        *,
        kind: str,
        namespace: str,
        name: str,
        version: str,
        input_payload: dict[str, Any],
    ) -> CapabilityExecutionResponse:
        """Invoke a nested capability under narrowed policy context."""


CapabilityHandler = Callable[
    [CapabilityInvocationRequest, CapabilityRuntime], CapabilityExecutionResponse
]


class CapabilityRegistry:
    """In-memory capability registry backed by discovery and direct registration."""

    def __init__(self) -> None:
        self._specs: dict[str, CapabilitySpec] = {}
        self._handlers: dict[str, CapabilityHandler] = {}

    def discover(self, *, root: Path) -> None:
        """Auto-discover ``capability.yaml`` declarations under one root."""
        if not root.exists():
            return
        for manifest_path in sorted(root.glob("*/*/capability.yaml")):
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            try:
                spec = CapabilitySpec.model_validate(raw)
            except Exception:  # noqa: BLE001
                continue
            self.register_spec(spec=spec)

    def register_spec(self, *, spec: CapabilitySpec) -> None:
        """Register one capability declaration without handler binding."""
        self._specs[spec.capability_id] = spec

    def register_handler(
        self,
        *,
        capability_id: str,
        handler: CapabilityHandler,
    ) -> None:
        """Register one runtime handler for a previously discovered capability."""
        self._handlers[capability_id] = handler

    def resolve_spec(self, *, capability_id: str) -> CapabilitySpec | None:
        """Resolve one capability declaration by canonical ID."""
        return self._specs.get(capability_id)

    def resolve_handler(self, *, capability_id: str) -> CapabilityHandler | None:
        """Resolve one capability handler by canonical ID."""
        return self._handlers.get(capability_id)

    def count(self) -> int:
        """Return number of discovered capability specs."""
        return len(self._specs)
