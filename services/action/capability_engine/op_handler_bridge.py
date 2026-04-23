"""Generic Op handler bridge: builds CapabilityHandlers from call_target strings."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from lib.shared.errors import ErrorDetail
from services.action.capability_engine.domain import CapabilityExecutionResponse
from services.action.capability_engine.registry import (
    CapabilityHandler,
    CapabilityRuntime,
)
from services.action.policy_service.domain import CapabilityInvocationRequest


class OpHandlerBridgeError(Exception):
    """Raised when a bridged Op handler encounters a structured service error."""

    def __init__(self, errors: tuple[ErrorDetail, ...]) -> None:
        self.errors = errors
        super().__init__(f"bridge error: {len(errors)} error(s)")


def build_op_handler(
    *,
    call_target: str,
    components: Mapping[str, object],
) -> CapabilityHandler:
    """Build a generic CapabilityHandler that delegates to a service method.

    ``call_target`` has the form ``"component_id.method_name"``.
    ``components`` is the runtime component map keyed by component_id.
    """
    _resolve_call_target(call_target=call_target, components=components)

    def handler(
        request: CapabilityInvocationRequest,
        runtime: CapabilityRuntime,
    ) -> CapabilityExecutionResponse:
        raw_payload = invoke_call_target(
            call_target=call_target,
            components=components,
            meta=request.metadata,
            input_payload=request.input_payload,
        )
        output = _unwrap_payload(raw_payload)
        return CapabilityExecutionResponse(output=output)

    return handler


def invoke_call_target(
    *,
    call_target: str,
    components: Mapping[str, object],
    meta: Any,
    input_payload: Mapping[str, Any],
) -> Any:
    """Invoke one service call target and return the raw envelope payload."""
    method, accepted, required = _resolve_call_target(
        call_target=call_target,
        components=components,
    )
    payload = dict(input_payload)
    unknown = set(payload.keys()) - set(accepted.keys())
    if unknown:
        raise ValueError(f"unknown input keys: {sorted(unknown)}")

    missing = required - set(payload.keys())
    if missing:
        raise ValueError(f"missing required input keys: {sorted(missing)}")

    envelope = method(meta=meta, **payload)

    if not envelope.ok:
        raise OpHandlerBridgeError(
            errors=tuple(envelope.errors),
        )

    return envelope.payload.value if envelope.payload is not None else None


def _resolve_call_target(
    *,
    call_target: str,
    components: Mapping[str, object],
) -> tuple[
    Callable[..., Any],
    dict[str, inspect.Parameter],
    set[str],
]:
    """Resolve one call target into a callable and its accepted parameters."""
    parts = call_target.split(".", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"invalid call_target format: {call_target!r}")

    component_id, method_name = parts

    service = components.get(component_id)
    if service is None:
        raise ValueError(f"component not found: {component_id!r}")

    method = getattr(service, method_name, None)
    if method is None or not callable(method):
        raise ValueError(
            f"method {method_name!r} not found on component {component_id!r}"
        )

    sig = inspect.signature(method)
    accepted: dict[str, inspect.Parameter] = {}
    for name, param in sig.parameters.items():
        if name in {"self", "meta"}:
            continue
        accepted[name] = param

    required = {
        name
        for name, param in accepted.items()
        if param.default is inspect.Parameter.empty
    }
    return method, accepted, required


def _unwrap_payload(value: Any) -> dict[str, Any] | None:
    """Convert a service return payload into a JSON-safe output dict."""
    if value is None:
        return None
    if isinstance(value, bool):
        return {"result": value}
    if isinstance(value, datetime):
        return {"result": value.isoformat()}
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return {
            "items": [
                item.model_dump(mode="json") if isinstance(item, BaseModel) else item
                for item in value
            ]
        }
    if isinstance(value, tuple):
        return {
            "items": [
                item.model_dump(mode="json") if isinstance(item, BaseModel) else item
                for item in value
            ]
        }
    return {"result": value}
