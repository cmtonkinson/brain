"""Core-level aggregate health evaluation utilities."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from pydantic import BaseModel, ConfigDict, Field

from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import EnvelopeKind, new_meta
from lib.shared.manifest import get_registry


class ComponentHealthResult(BaseModel):
    """One component-level readiness result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ready: bool
    detail: str = ""


class CoreHealthResult(BaseModel):
    """Aggregate core readiness across services and shared resources."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ready: bool
    services: dict[str, ComponentHealthResult] = Field(default_factory=dict)
    resources: dict[str, ComponentHealthResult] = Field(default_factory=dict)


def evaluate_core_health(
    *,
    settings: CoreRuntimeSettings,
    components: Mapping[str, object],
) -> CoreHealthResult:
    """Evaluate aggregate core health from instantiated components."""
    registry = get_registry()
    max_timeout_seconds = settings.core.health.max_timeout_seconds

    service_results = _evaluate_manifests(
        registry.list_services(), components, max_timeout_seconds
    )
    resource_results = _evaluate_manifests(
        registry.list_resources(), components, max_timeout_seconds
    )

    overall_ready = all(item.ready for item in service_results.values()) and all(
        item.ready for item in resource_results.values()
    )
    return CoreHealthResult(
        ready=overall_ready,
        services=service_results,
        resources=resource_results,
    )


def _evaluate_manifests(
    manifests: Iterable[object],
    components: Mapping[str, object],
    max_timeout_seconds: float,
) -> dict[str, ComponentHealthResult]:
    """Evaluate health for a sequence of component manifests."""
    results: dict[str, ComponentHealthResult] = {}
    for manifest in manifests:
        component_id = str(manifest.id)
        component = components.get(component_id)
        if component is None:
            results[component_id] = ComponentHealthResult(
                ready=False,
                detail="component not instantiated",
            )
            continue
        results[component_id] = _evaluate_component_health(
            component_id=component_id,
            component=component,
            max_timeout_seconds=max_timeout_seconds,
        )
    return results


def _evaluate_component_health(
    *,
    component_id: str,
    component: object,
    max_timeout_seconds: float,
) -> ComponentHealthResult:
    """Evaluate one component health with global timeout enforcement."""
    health_fn = getattr(component, "health", None)
    if not callable(health_fn):
        return ComponentHealthResult(
            ready=False,
            detail="component does not expose health()",
        )

    call: Callable[[], object]
    if _health_accepts_meta(health_fn):
        meta = new_meta(
            kind=EnvelopeKind.RESULT,
            source="core_health",
            principal="system",
        )

        def _call_with_meta() -> object:
            return health_fn(meta=meta)

        call = _call_with_meta
    else:
        call = health_fn

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(call)
        try:
            result = future.result(timeout=max_timeout_seconds)
        except FutureTimeoutError:
            return ComponentHealthResult(
                ready=False,
                detail=(
                    f"health() exceeded global max timeout ({max_timeout_seconds:.3f}s)"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return ComponentHealthResult(
                ready=False,
                detail=f"health() raised {type(exc).__name__}",
            )

    ready, detail = _coerce_health_result(result)
    return ComponentHealthResult(ready=ready, detail=detail or "ok")


def _health_accepts_meta(health_fn: Callable[..., object]) -> bool:
    """Return True when callable health function accepts ``meta``."""
    try:
        signature = inspect.signature(health_fn)
    except TypeError, ValueError:
        return False
    parameters = signature.parameters
    if "meta" in parameters:
        return True
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


def _coerce_health_result(result: object) -> tuple[bool, str]:
    """Normalize heterogeneous health return shapes into ready/detail."""
    if isinstance(result, bool):
        return result, "ok" if result else "not ready"

    if hasattr(result, "ok") and hasattr(result, "payload"):
        ready = _is_envelope_ready(result)
        detail = _health_detail(envelope=result)
        return ready, detail

    if hasattr(result, "model_dump"):
        values = result.model_dump(mode="python")
    elif isinstance(result, dict):
        values = result
    else:
        return False, "health() returned unsupported result"

    ready_value = values.get("ready")
    if isinstance(ready_value, bool):
        detail_value = values.get("detail")
        return ready_value, detail_value if isinstance(detail_value, str) else ""

    ready_fields = [
        value
        for key, value in values.items()
        if key.endswith("_ready") and isinstance(value, bool)
    ]
    if ready_fields:
        detail_value = values.get("detail")
        return all(ready_fields), detail_value if isinstance(detail_value, str) else ""

    return False, "health() result missing readiness fields"


def _is_envelope_ready(envelope: object) -> bool:
    """Return readiness based on envelope ``ok`` and payload *_ready fields."""
    ok = bool(getattr(envelope, "ok", False))
    if not ok:
        return False

    payload_wrapper = getattr(envelope, "payload", None)
    if payload_wrapper is None:
        return True
    payload = getattr(payload_wrapper, "value", None)
    if payload is None:
        return True

    if hasattr(payload, "model_dump"):
        values = payload.model_dump(mode="python")
    elif isinstance(payload, dict):
        values = payload
    else:
        return True

    for key, value in values.items():
        if key.endswith("_ready") and isinstance(value, bool) and not value:
            return False
    return True


def _health_detail(*, envelope: object) -> str:
    """Extract a concise detail string from one health envelope."""
    payload_wrapper = getattr(envelope, "payload", None)
    if payload_wrapper is not None:
        payload = getattr(payload_wrapper, "value", None)
        if payload is not None and hasattr(payload, "model_dump"):
            payload_values = payload.model_dump(mode="python")
            detail = payload_values.get("detail")
            if isinstance(detail, str):
                return detail

    errors = getattr(envelope, "errors", ())
    if isinstance(errors, list) and len(errors) > 0:
        first = errors[0]
        message = getattr(first, "message", "")
        if isinstance(message, str):
            return message
    return ""
