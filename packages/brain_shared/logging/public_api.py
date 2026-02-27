"""Composable instrumentation helpers for public API methods.

This module defines a general-purpose instrumentation decorator with concern
hooks so logging, tracing, metrics, and future observability behaviors can
share one stable callsite contract.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache, wraps
from time import perf_counter
from typing import Any, Callable, Mapping, Protocol, Sequence

from packages.brain_shared.config import load_core_settings

from . import fields
from .context import log_context

_QDRANT_COMPONENT_ID = "substrate_qdrant"
_DEFAULT_METER_NAME = "brain.public_api"
_DEFAULT_TRACER_NAME = "brain.public_api"
_DEFAULT_METRIC_PUBLIC_API_CALLS_TOTAL = "brain_public_api_calls_total"
_DEFAULT_METRIC_PUBLIC_API_DURATION_MS = "brain_public_api_duration_ms"
_DEFAULT_METRIC_PUBLIC_API_ERRORS_TOTAL = "brain_public_api_errors_total"
_DEFAULT_METRIC_INSTRUMENTATION_FAILURES_TOTAL = (
    "brain_public_api_instrumentation_failures_total"
)
_DEFAULT_METRIC_QDRANT_OPS_TOTAL = "brain_qdrant_ops_total"
_DEFAULT_METRIC_QDRANT_OP_DURATION_MS = "brain_qdrant_op_duration_ms"


@dataclass(frozen=True)
class InvocationContext:
    """Structured metadata describing one public API invocation."""

    component_id: str
    api_name: str
    trace_id: str | None
    envelope_id: str | None
    principal: str | None
    references: Mapping[str, str]


@dataclass(frozen=True)
class CompletionContext:
    """Structured metadata describing one completed public API invocation."""

    invocation: InvocationContext
    success: bool
    duration_ms: float
    errors: list[str]
    error_categories: list[str]


class PublicApiInstrumentationConcern(Protocol):
    """Hook contract for one public API instrumentation concern."""

    def on_invocation(self, context: InvocationContext) -> None:
        """Handle invocation-start event for one method call."""

    def on_completion(self, context: CompletionContext) -> None:
        """Handle completion event for one method call."""


class PublicApiLoggingConcern:
    """Logging concern implementation for invocation/completion events."""

    def __init__(self, *, logger: Any) -> None:
        self._logger = logger

    def on_invocation(self, context: InvocationContext) -> None:
        """Emit standardized structured invocation-start log."""
        with log_context(_invocation_log_context(context)):
            self._logger.info("Public API invocation")

    def on_completion(self, context: CompletionContext) -> None:
        """Emit standardized structured completion log."""
        payload = _invocation_log_context(context.invocation)
        payload.update(
            {
                fields.EVENT: fields.PUBLIC_API_COMPLETION_EVENT,
                fields.SUCCESS: context.success,
                fields.DURATION_MS: context.duration_ms,
                fields.ERRORS: context.errors,
            }
        )
        with log_context(payload):
            if context.success:
                self._logger.info("Public API completion")
            else:
                self._logger.warning("Public API completion")


class _CounterLike(Protocol):
    """Minimal counter interface used by metrics concern."""

    def add(self, amount: int | float, attributes: Mapping[str, str]) -> None:
        """Record one counter increment with attributes."""


class _HistogramLike(Protocol):
    """Minimal histogram interface used by metrics concern."""

    def record(self, amount: float, attributes: Mapping[str, str]) -> None:
        """Record one sample with attributes."""


class _SpanLike(Protocol):
    """Minimal span interface used by tracing concern."""

    def set_attribute(self, key: str, value: object) -> None:
        """Attach one attribute to a span."""

    def record_exception(self, exception: Exception) -> None:
        """Record one exception on a span."""

    def set_status(self, status: object) -> None:
        """Set the status of a span."""


class _SpanContextManagerLike(Protocol):
    """Minimal context manager interface for span lifecycles."""

    def __enter__(self) -> _SpanLike:
        """Enter and return the active span."""

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Exit and close the active span."""


class _TracerLike(Protocol):
    """Minimal tracer interface used by tracing concern."""

    def start_as_current_span(self, name: str) -> _SpanContextManagerLike:
        """Start one span and return a context manager."""


@dataclass(frozen=True)
class _TraceScope:
    """One in-flight trace scope for a decorated API invocation."""

    manager: _SpanContextManagerLike
    span: _SpanLike


class PublicApiTracingConcern:
    """Tracing concern implementation for public API invocation telemetry."""

    def __init__(self, *, tracer: _TracerLike) -> None:
        self._tracer = tracer
        self._active_scopes: ContextVar[list[_TraceScope]] = ContextVar(
            "public_api_tracing_scopes", default=[]
        )

    def on_invocation(self, context: InvocationContext) -> None:
        """Start one span for the current invocation and attach metadata."""
        manager = self._tracer.start_as_current_span(
            f"public_api.{context.component_id}.{context.api_name}"
        )
        span = manager.__enter__()
        span.set_attribute(fields.COMPONENT_ID, context.component_id)
        span.set_attribute(fields.API_NAME, context.api_name)
        if context.trace_id is not None:
            span.set_attribute(fields.TRACE_ID, context.trace_id)
        if context.envelope_id is not None:
            span.set_attribute(fields.ENVELOPE_ID, context.envelope_id)
        if context.principal is not None:
            span.set_attribute(fields.PRINCIPAL, context.principal)
        for key, value in context.references.items():
            span.set_attribute(f"reference.{key}", value)

        current = self._active_scopes.get()
        self._active_scopes.set([*current, _TraceScope(manager=manager, span=span)])

    def on_completion(self, context: CompletionContext) -> None:
        """Finalize the current invocation span with completion metadata."""
        current = self._active_scopes.get()
        if len(current) == 0:
            return
        scope = current[-1]
        self._active_scopes.set(current[:-1])

        scope.span.set_attribute(fields.SUCCESS, context.success)
        scope.span.set_attribute(fields.DURATION_MS, context.duration_ms)
        scope.span.set_attribute(
            fields.OUTCOME, "success" if context.success else "failure"
        )
        scope.span.set_attribute("errors.count", len(context.errors))

        if not context.success:
            _set_span_error_status(scope.span)
            if len(context.errors) > 0:
                scope.span.record_exception(RuntimeError("; ".join(context.errors[:3])))
        scope.manager.__exit__(None, None, None)


class PublicApiMetricsConcern:
    """Metrics concern implementation for public API invocation telemetry."""

    def __init__(
        self,
        *,
        public_api_calls_total: _CounterLike,
        public_api_duration_ms: _HistogramLike,
        public_api_errors_total: _CounterLike,
        qdrant_ops_total: _CounterLike,
        qdrant_op_duration_ms: _HistogramLike,
    ) -> None:
        self._public_api_calls_total = public_api_calls_total
        self._public_api_duration_ms = public_api_duration_ms
        self._public_api_errors_total = public_api_errors_total
        self._qdrant_ops_total = qdrant_ops_total
        self._qdrant_op_duration_ms = qdrant_op_duration_ms

    def on_invocation(self, context: InvocationContext) -> None:
        """No-op at invocation; metrics are emitted on completion."""
        del context

    def on_completion(self, context: CompletionContext) -> None:
        """Emit counters/histograms for completed invocation outcomes."""
        outcome = "success" if context.success else "failure"
        attrs = {
            fields.COMPONENT_ID: context.invocation.component_id,
            fields.API_NAME: context.invocation.api_name,
            fields.OUTCOME: outcome,
        }
        self._public_api_calls_total.add(1, attributes=attrs)
        self._public_api_duration_ms.record(context.duration_ms, attributes=attrs)

        if context.invocation.component_id == _QDRANT_COMPONENT_ID:
            self._qdrant_ops_total.add(
                1,
                attributes={
                    fields.API_NAME: context.invocation.api_name,
                    fields.OUTCOME: outcome,
                },
            )
            self._qdrant_op_duration_ms.record(
                context.duration_ms,
                attributes={
                    fields.API_NAME: context.invocation.api_name,
                    fields.OUTCOME: outcome,
                },
            )

        if context.success:
            return

        categories = context.error_categories or ["unknown"]
        for category in categories:
            self._public_api_errors_total.add(
                1,
                attributes={
                    fields.COMPONENT_ID: context.invocation.component_id,
                    fields.API_NAME: context.invocation.api_name,
                    fields.ERROR_CATEGORY: category,
                },
            )


def public_api_instrumented(
    *,
    component_id: str,
    api_name: str | None = None,
    id_fields: tuple[str, ...] = (),
    concerns: Sequence[PublicApiInstrumentationConcern] | None = None,
    logger: Any | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate one public API method with composable instrumentation concerns."""

    resolved_concerns: tuple[PublicApiInstrumentationConcern, ...] = tuple(
        concerns or ()
    )
    default_tracing_concern = _default_public_api_tracing_concern()
    if default_tracing_concern is not None:
        resolved_concerns = (*resolved_concerns, default_tracing_concern)
    default_metrics_concern = _default_public_api_metrics_concern()
    if default_metrics_concern is not None:
        resolved_concerns = (*resolved_concerns, default_metrics_concern)
    if logger is not None:
        resolved_concerns = (PublicApiLoggingConcern(logger=logger), *resolved_concerns)
    if len(resolved_concerns) == 0:
        raise ValueError("public_api_instrumented requires at least one concern")

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        method_name = api_name or func.__name__

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            meta = kwargs.get("meta")
            references = {
                name: str(kwargs[name])
                for name in id_fields
                if kwargs.get(name) not in (None, "")
            }
            invocation = InvocationContext(
                component_id=component_id,
                api_name=method_name,
                trace_id=_attr_or_none(meta, "trace_id"),
                envelope_id=_attr_or_none(meta, "envelope_id"),
                principal=_attr_or_none(meta, "principal"),
                references=references,
            )
            _emit_invocation(
                concerns=resolved_concerns,
                context=invocation,
                logger=logger,
            )

            started = perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                completion = CompletionContext(
                    invocation=invocation,
                    success=False,
                    duration_ms=round((perf_counter() - started) * 1000.0, 3),
                    errors=[f"{type(exc).__name__}: {exc}"],
                    error_categories=["internal"],
                )
                _emit_completion(
                    concerns=resolved_concerns,
                    context=completion,
                    logger=logger,
                )
                raise

            success, errors = _result_summary(result)
            completion = CompletionContext(
                invocation=invocation,
                success=success,
                duration_ms=round((perf_counter() - started) * 1000.0, 3),
                errors=errors,
                error_categories=_result_error_categories(result),
            )
            _emit_completion(
                concerns=resolved_concerns,
                context=completion,
                logger=logger,
            )
            return result

        return wrapper

    return decorator


def public_api_logged(
    *,
    logger: Any,
    component_id: str,
    api_name: str | None = None,
    id_fields: tuple[str, ...] = (),
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Backwards-compatible logging-only wrapper over instrumentation decorator."""
    return public_api_instrumented(
        logger=logger,
        component_id=component_id,
        api_name=api_name,
        id_fields=id_fields,
        concerns=(),
    )


def _attr_or_none(obj: object | None, name: str) -> str | None:
    """Return string attribute value from object when present."""
    if obj is None:
        return None
    value = getattr(obj, name, None)
    if value in (None, ""):
        return None
    return str(value)


def _result_summary(result: object) -> tuple[bool, list[str]]:
    """Infer success and sanitized error summaries from a result value."""
    errors_obj = getattr(result, "errors", [])
    errors = _sanitize_errors(errors_obj)
    ok_value = getattr(result, "ok", None)
    if isinstance(ok_value, bool):
        return ok_value, errors
    return len(errors) == 0, errors


def _result_error_categories(result: object) -> list[str]:
    """Infer normalized error categories from a result-like object."""
    errors_obj = getattr(result, "errors", [])
    if not isinstance(errors_obj, list):
        return []
    categories: list[str] = []
    for item in errors_obj:
        category = None
        if isinstance(item, Mapping):
            category = item.get("category")
        else:
            raw = getattr(item, "category", None)
            category = getattr(raw, "value", raw)
        if category in (None, ""):
            continue
        categories.append(str(category))
    return categories


def _sanitize_errors(errors: object) -> list[str]:
    """Return safe one-line error summaries for logs."""
    if not isinstance(errors, list):
        return []
    summaries: list[str] = []
    for item in errors:
        if isinstance(item, Mapping):
            code = item.get("code")
            message = item.get("message")
        else:
            code = getattr(item, "code", None)
            message = getattr(item, "message", None)
        if message in (None, ""):
            continue
        if code in (None, ""):
            summaries.append(str(message))
        else:
            summaries.append(f"{code}: {message}")
    return summaries


def _invocation_log_context(context: InvocationContext) -> dict[str, object]:
    """Build common structured fields for one invocation event."""
    return {
        fields.EVENT: fields.PUBLIC_API_INVOCATION_EVENT,
        fields.COMPONENT_ID: context.component_id,
        fields.API_NAME: context.api_name,
        fields.TRACE_ID: context.trace_id,
        fields.ENVELOPE_ID: context.envelope_id,
        fields.PRINCIPAL: context.principal,
        **context.references,
    }


def _emit_invocation(
    *,
    concerns: Sequence[PublicApiInstrumentationConcern],
    context: InvocationContext,
    logger: Any | None,
) -> None:
    """Dispatch invocation event to concerns with failure isolation."""
    for concern in concerns:
        try:
            concern.on_invocation(context)
        except Exception as exc:  # noqa: BLE001
            _log_concern_failure(
                logger=logger,
                event=fields.PUBLIC_API_INSTRUMENTATION_FAILURE_EVENT,
                stage="invocation",
                concern=type(concern).__name__,
                exc=exc,
                invocation=context,
            )


def _emit_completion(
    *,
    concerns: Sequence[PublicApiInstrumentationConcern],
    context: CompletionContext,
    logger: Any | None,
) -> None:
    """Dispatch completion event to concerns with failure isolation."""
    for concern in concerns:
        try:
            concern.on_completion(context)
        except Exception as exc:  # noqa: BLE001
            _log_concern_failure(
                logger=logger,
                event=fields.PUBLIC_API_INSTRUMENTATION_FAILURE_EVENT,
                stage="completion",
                concern=type(concern).__name__,
                exc=exc,
                invocation=context.invocation,
            )


def _log_concern_failure(
    *,
    logger: Any | None,
    event: str,
    stage: str,
    concern: str,
    exc: Exception,
    invocation: InvocationContext,
) -> None:
    """Best-effort warning log for instrumentation concern hook failures."""
    if logger is None:
        return
    with log_context(
        {
            fields.EVENT: event,
            fields.COMPONENT_ID: invocation.component_id,
            fields.API_NAME: invocation.api_name,
            fields.STAGE: stage,
            fields.CONCERN: concern,
            fields.ERRORS: [f"{type(exc).__name__}: {exc}"],
        }
    ):
        logger.warning("Public API instrumentation concern failed")
    _record_instrumentation_failure(
        stage=stage,
        concern=concern,
        component_id=invocation.component_id,
        api_name=invocation.api_name,
    )


def _set_span_error_status(span: _SpanLike) -> None:
    """Best-effort OTel error status update when tracing API is available."""
    try:
        from opentelemetry.trace.status import Status, StatusCode

        span.set_status(Status(StatusCode.ERROR))
    except ImportError:
        return


@lru_cache(maxsize=1)
def _default_public_api_tracing_concern() -> PublicApiTracingConcern | None:
    """Build a default OTel-backed public API tracing concern when available."""
    try:
        from opentelemetry import trace as otel_trace
    except ImportError:
        return None
    names = _public_api_otel_names()
    return PublicApiTracingConcern(tracer=otel_trace.get_tracer(names.tracer_name))


@lru_cache(maxsize=1)
def _default_public_api_metrics_concern() -> PublicApiMetricsConcern | None:
    """Build a default OTel-backed public API metrics concern when available."""
    instruments = _default_otel_instruments()
    if instruments is None:
        return None
    return PublicApiMetricsConcern(
        public_api_calls_total=instruments.public_api_calls_total,
        public_api_duration_ms=instruments.public_api_duration_ms,
        public_api_errors_total=instruments.public_api_errors_total,
        qdrant_ops_total=instruments.qdrant_ops_total,
        qdrant_op_duration_ms=instruments.qdrant_op_duration_ms,
    )


@dataclass(frozen=True)
class _OtelInstruments:
    """Resolved OTel instruments used by public API metrics concern."""

    public_api_calls_total: _CounterLike
    public_api_duration_ms: _HistogramLike
    public_api_errors_total: _CounterLike
    instrumentation_failures_total: _CounterLike
    qdrant_ops_total: _CounterLike
    qdrant_op_duration_ms: _HistogramLike


@dataclass(frozen=True)
class _PublicApiOtelNames:
    """Resolved OTel naming for public API tracer and metric instruments."""

    meter_name: str
    tracer_name: str
    metric_public_api_calls_total: str
    metric_public_api_duration_ms: str
    metric_public_api_errors_total: str
    metric_instrumentation_failures_total: str
    metric_qdrant_ops_total: str
    metric_qdrant_op_duration_ms: str


@lru_cache(maxsize=1)
def _public_api_otel_names() -> _PublicApiOtelNames:
    """Resolve OTel names from config with safe built-in defaults."""
    otel = load_core_settings().observability.public_api.otel.model_dump(mode="python")

    return _PublicApiOtelNames(
        meter_name=_configured_name(otel, "meter_name", _DEFAULT_METER_NAME),
        tracer_name=_configured_name(otel, "tracer_name", _DEFAULT_TRACER_NAME),
        metric_public_api_calls_total=_configured_name(
            otel,
            "metric_public_api_calls_total",
            _DEFAULT_METRIC_PUBLIC_API_CALLS_TOTAL,
        ),
        metric_public_api_duration_ms=_configured_name(
            otel,
            "metric_public_api_duration_ms",
            _DEFAULT_METRIC_PUBLIC_API_DURATION_MS,
        ),
        metric_public_api_errors_total=_configured_name(
            otel,
            "metric_public_api_errors_total",
            _DEFAULT_METRIC_PUBLIC_API_ERRORS_TOTAL,
        ),
        metric_instrumentation_failures_total=_configured_name(
            otel,
            "metric_instrumentation_failures_total",
            _DEFAULT_METRIC_INSTRUMENTATION_FAILURES_TOTAL,
        ),
        metric_qdrant_ops_total=_configured_name(
            otel,
            "metric_qdrant_ops_total",
            _DEFAULT_METRIC_QDRANT_OPS_TOTAL,
        ),
        metric_qdrant_op_duration_ms=_configured_name(
            otel,
            "metric_qdrant_op_duration_ms",
            _DEFAULT_METRIC_QDRANT_OP_DURATION_MS,
        ),
    )


def _configured_name(mapping: Mapping[str, object], key: str, default: str) -> str:
    """Return non-empty string from mapping, otherwise fallback default."""
    value = str(mapping.get(key, default)).strip()
    if value == "":
        return default
    return value


@lru_cache(maxsize=1)
def _default_otel_instruments() -> _OtelInstruments | None:
    """Create OTel metric instruments when opentelemetry is installed."""
    try:
        from opentelemetry import metrics as otel_metrics
    except ImportError:
        return None

    names = _public_api_otel_names()
    meter = otel_metrics.get_meter(names.meter_name)
    return _OtelInstruments(
        public_api_calls_total=meter.create_counter(
            name=names.metric_public_api_calls_total,
            description="Count of public API invocations by component/method/outcome.",
            unit="1",
        ),
        public_api_duration_ms=meter.create_histogram(
            name=names.metric_public_api_duration_ms,
            description="Public API invocation latency in milliseconds.",
            unit="ms",
        ),
        public_api_errors_total=meter.create_counter(
            name=names.metric_public_api_errors_total,
            description="Count of public API failures by error category.",
            unit="1",
        ),
        instrumentation_failures_total=meter.create_counter(
            name=names.metric_instrumentation_failures_total,
            description="Count of instrumentation concern failures.",
            unit="1",
        ),
        qdrant_ops_total=meter.create_counter(
            name=names.metric_qdrant_ops_total,
            description="Count of Qdrant substrate operations by outcome.",
            unit="1",
        ),
        qdrant_op_duration_ms=meter.create_histogram(
            name=names.metric_qdrant_op_duration_ms,
            description="Qdrant substrate operation latency in milliseconds.",
            unit="ms",
        ),
    )


def _record_instrumentation_failure(
    *, stage: str, concern: str, component_id: str, api_name: str
) -> None:
    """Best-effort metric emission for instrumentation concern failures."""
    instruments = _default_otel_instruments()
    if instruments is None:
        return
    instruments.instrumentation_failures_total.add(
        1,
        attributes={
            fields.COMPONENT_ID: component_id,
            fields.API_NAME: api_name,
            fields.STAGE: stage,
            fields.CONCERN: concern,
        },
    )
