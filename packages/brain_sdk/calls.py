"""Thin typed wrappers for Brain Core SDK HTTP operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from packages.brain_sdk.errors import (
    BrainTransportError,
    map_transport_error,
)
from packages.brain_shared.http.errors import HttpRequestError, HttpStatusError


@dataclass(frozen=True, slots=True)
class CoreComponentHealth:
    """Aggregate readiness for one Core component."""

    ready: bool
    detail: str


@dataclass(frozen=True, slots=True)
class CoreHealthResult:
    """Aggregate Core health status."""

    ready: bool
    services: dict[str, CoreComponentHealth]
    resources: dict[str, CoreComponentHealth]


def call_core_health(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
) -> CoreHealthResult:
    """Execute one Core health request and map response payload."""
    data = _post_json(
        operation="core.health",
        http=http,
        url="/health",
        body=metadata,
        timeout_seconds=timeout_seconds,
        method="get",
    )
    services = {
        k: CoreComponentHealth(
            ready=bool(v.get("ready")), detail=str(v.get("detail", ""))
        )
        for k, v in data.get("services", {}).items()
    }
    resources = {
        k: CoreComponentHealth(
            ready=bool(v.get("ready")), detail=str(v.get("detail", ""))
        )
        for k, v in data.get("resources", {}).items()
    }
    return CoreHealthResult(
        ready=bool(data.get("ready")),
        services=services,
        resources=resources,
    )


def _post_json(
    *,
    operation: str,
    http: object,
    url: str,
    body: dict[str, object],
    timeout_seconds: float,
    method: str = "post",
) -> dict[str, Any]:
    """Issue one HTTP request and return the JSON response dict."""
    try:
        if method == "get":
            return http.get_json(url, timeout=timeout_seconds)  # type: ignore[union-attr]
        return http.post_json(url, json=body, timeout=timeout_seconds)  # type: ignore[union-attr]
    except HttpStatusError as exc:
        retryable = exc.status_code >= 500 or exc.status_code == 429
        raise map_transport_error(
            operation=operation,
            status_code=exc.status_code,
            message=exc.response_body or str(exc),
            retryable=retryable,
        ) from exc
    except HttpRequestError as exc:
        raise BrainTransportError(
            message=f"{operation} transport failure: {exc}",
            operation=operation,
            status_code=0,
            retryable=True,
        ) from exc


def core_health(
    *,
    client: object,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> CoreHealthResult:
    """High-level SDK wrapper for Core health checks."""
    return client.core_health(  # type: ignore[union-attr]
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        )
    )


def _meta_overrides(
    *,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> object:
    """Build metadata overrides only when call-site values are provided."""
    from packages.brain_sdk.meta import MetaOverrides

    has_values = any(
        (
            principal != "",
            source != "",
            trace_id is not None,
            parent_id is not None,
        )
    )
    if not has_values:
        return None
    return MetaOverrides(
        principal=principal or None,
        source=source or None,
        trace_id=trace_id,
        parent_id="" if parent_id is None else parent_id,
    )
