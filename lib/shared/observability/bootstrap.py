"""OpenTelemetry bootstrap for Brain runtime processes."""

from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from lib.shared.config import ObservabilitySettings
from lib.shared.logging import get_logger

if TYPE_CHECKING:
    from pydantic_ai.models.instrumented import InstrumentationSettings

_LOGGER = get_logger(__name__)
try:
    _SERVICE_VERSION = importlib.metadata.version("brain")
except importlib.metadata.PackageNotFoundError:
    _SERVICE_VERSION = "0.0.0"
_OTLP_TRACES_SUFFIX = "/v1/traces"
_OTLP_METRICS_SUFFIX = "/v1/metrics"
_BOOTSTRAPPED = False
_LLM_CONTENT_CAPTURE_ENABLED = False
_BOOTSTRAP_RESULT: "ObservabilityBootstrapResult | None" = None


@dataclass(frozen=True, slots=True)
class ObservabilityBootstrapResult:
    """Result of one observability bootstrap attempt."""

    enabled: bool
    traces_enabled: bool
    metrics_enabled: bool
    instrumented_httpx: bool
    error: str | None = None


def is_observability_enabled() -> bool:
    """Return whether process-level observability has been bootstrapped."""
    return _BOOTSTRAPPED


def is_llm_content_capture_enabled() -> bool:
    """Return whether LLM telemetry may include prompt and completion content."""
    return _BOOTSTRAPPED and _LLM_CONTENT_CAPTURE_ENABLED


def bootstrap_observability(
    *,
    settings: ObservabilitySettings,
    service_name: str,
    environment: str = "dev",
    service_version: str = _SERVICE_VERSION,
) -> ObservabilityBootstrapResult:
    """Initialize OpenTelemetry providers and common instrumentation once.

    Idempotent: a second call returns the result captured at first bootstrap.
    The supplied ``settings`` are not re-applied; reconfiguration requires a
    process restart (or explicit ``reset_for_tests`` between unit tests).
    """
    global _BOOTSTRAPPED, _LLM_CONTENT_CAPTURE_ENABLED, _BOOTSTRAP_RESULT
    if not settings.enabled:
        return ObservabilityBootstrapResult(
            enabled=False,
            traces_enabled=False,
            metrics_enabled=False,
            instrumented_httpx=False,
        )
    if _BOOTSTRAPPED and _BOOTSTRAP_RESULT is not None:
        return _BOOTSTRAP_RESULT

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
        from opentelemetry.semconv.resource import ResourceAttributes
    except ImportError as exc:
        _LOGGER.warning(
            "observability dependencies unavailable",
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )
        return ObservabilityBootstrapResult(
            enabled=False,
            traces_enabled=False,
            metrics_enabled=False,
            instrumented_httpx=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    try:
        resource = Resource.create(
            {
                ResourceAttributes.SERVICE_NAME: service_name,
                ResourceAttributes.SERVICE_VERSION: service_version,
                ResourceAttributes.DEPLOYMENT_ENVIRONMENT: environment,
            }
        )
        headers = dict(settings.otlp.headers)
        if settings.traces.enabled:
            trace_provider = TracerProvider(
                resource=resource,
                sampler=TraceIdRatioBased(settings.traces.sample_ratio),
            )
            trace_provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(
                        endpoint=_otlp_endpoint(
                            settings.otlp.endpoint, _OTLP_TRACES_SUFFIX
                        ),
                        headers=headers,
                    )
                )
            )
            trace.set_tracer_provider(trace_provider)

        if settings.metrics.enabled:
            metric_reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(
                    endpoint=_otlp_endpoint(
                        settings.otlp.endpoint, _OTLP_METRICS_SUFFIX
                    ),
                    headers=headers,
                )
            )
            metrics.set_meter_provider(
                MeterProvider(resource=resource, metric_readers=[metric_reader])
            )

        HTTPXClientInstrumentor().instrument()
        _BOOTSTRAPPED = True
        _LLM_CONTENT_CAPTURE_ENABLED = bool(
            settings.llm.enabled and settings.llm.capture_content
        )
        _LOGGER.info(
            "observability initialized",
            extra={
                "service_name": service_name,
                "environment": environment,
                "otlp_endpoint": settings.otlp.endpoint,
                "traces_enabled": settings.traces.enabled,
                "metrics_enabled": settings.metrics.enabled,
            },
        )
        result = ObservabilityBootstrapResult(
            enabled=True,
            traces_enabled=settings.traces.enabled,
            metrics_enabled=settings.metrics.enabled,
            instrumented_httpx=True,
        )
        _BOOTSTRAP_RESULT = result
        return result
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning(
            "observability initialization failed",
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )
        return ObservabilityBootstrapResult(
            enabled=False,
            traces_enabled=False,
            metrics_enabled=False,
            instrumented_httpx=False,
            error=f"{type(exc).__name__}: {exc}",
        )


def pydantic_ai_instrumentation_settings(
    settings: ObservabilitySettings,
) -> InstrumentationSettings | None:
    """Return PydanticAI instrumentation settings when LLM telemetry is enabled."""
    if not settings.enabled or not settings.llm.enabled:
        return None
    return _build_pydantic_ai_instrumentation_settings(
        include_content=settings.llm.capture_content
    )


@lru_cache(maxsize=2)  # bool param → 2 possible cache entries
def _build_pydantic_ai_instrumentation_settings(
    *, include_content: bool
) -> InstrumentationSettings:
    """Build PydanticAI instrumentation settings without importing at module load."""
    from pydantic_ai.models.instrumented import InstrumentationSettings

    return InstrumentationSettings(
        include_content=include_content,
        include_binary_content=include_content,
    )


def _otlp_endpoint(base: str, suffix: str) -> str:
    """Resolve one OTLP HTTP signal endpoint from a base collector endpoint."""
    endpoint = base.strip().rstrip("/")
    if endpoint == "":
        raise ValueError(
            "otlp.endpoint must be a non-empty absolute URL; "
            "configure observability.otlp.endpoint or disable telemetry"
        )
    if endpoint.endswith(suffix):
        return endpoint
    return f"{endpoint}{suffix}"


def reset_for_tests() -> None:
    """Reset process-local bootstrap state for unit tests."""
    global _BOOTSTRAPPED, _LLM_CONTENT_CAPTURE_ENABLED, _BOOTSTRAP_RESULT
    _BOOTSTRAPPED = False
    _LLM_CONTENT_CAPTURE_ENABLED = False
    _BOOTSTRAP_RESULT = None
    _build_pydantic_ai_instrumentation_settings.cache_clear()
