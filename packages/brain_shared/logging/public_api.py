"""Composable instrumentation helpers for public API methods.

This module defines a general-purpose instrumentation decorator with concern
hooks so logging, tracing, metrics, and future observability behaviors can
share one stable callsite contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache, wraps
from time import perf_counter
from typing import Any, Callable, Mapping, Protocol, Sequence

from . import fields
from .context import log_context


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
                fields.EVENT: "public_api_completion",
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
            "component_id": context.invocation.component_id,
            "api_name": context.invocation.api_name,
            "outcome": outcome,
        }
        self._public_api_calls_total.add(1, attributes=attrs)
        self._public_api_duration_ms.record(context.duration_ms, attributes=attrs)

        if context.invocation.component_id == "substrate_qdrant":
            self._qdrant_ops_total.add(
                1,
                attributes={
                    "api_name": context.invocation.api_name,
                    "outcome": outcome,
                },
            )
            self._qdrant_op_duration_ms.record(
                context.duration_ms,
                attributes={
                    "api_name": context.invocation.api_name,
                    "outcome": outcome,
                },
            )

        if context.success:
            return

        categories = context.error_categories or ["unknown"]
        for category in categories:
            self._public_api_errors_total.add(
                1,
                attributes={
                    "component_id": context.invocation.component_id,
                    "api_name": context.invocation.api_name,
                    "error_category": category,
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
        fields.EVENT: "public_api_invocation",
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
                event="public_api_instrumentation_failure",
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
                event="public_api_instrumentation_failure",
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
            "stage": stage,
            "concern": concern,
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


@lru_cache(maxsize=1)
def _default_otel_instruments() -> _OtelInstruments | None:
    """Create OTel metric instruments when opentelemetry is installed."""
    try:
        from opentelemetry import metrics as otel_metrics
    except ImportError:
        return None

    meter = otel_metrics.get_meter("brain.public_api")
    return _OtelInstruments(
        public_api_calls_total=meter.create_counter(
            name="brain_public_api_calls_total",
            description="Count of public API invocations by component/method/outcome.",
            unit="1",
        ),
        public_api_duration_ms=meter.create_histogram(
            name="brain_public_api_duration_ms",
            description="Public API invocation latency in milliseconds.",
            unit="ms",
        ),
        public_api_errors_total=meter.create_counter(
            name="brain_public_api_errors_total",
            description="Count of public API failures by error category.",
            unit="1",
        ),
        instrumentation_failures_total=meter.create_counter(
            name="brain_public_api_instrumentation_failures_total",
            description="Count of instrumentation concern failures.",
            unit="1",
        ),
        qdrant_ops_total=meter.create_counter(
            name="brain_qdrant_ops_total",
            description="Count of Qdrant substrate operations by outcome.",
            unit="1",
        ),
        qdrant_op_duration_ms=meter.create_histogram(
            name="brain_qdrant_op_duration_ms",
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
            "component_id": component_id,
            "api_name": api_name,
            "stage": stage,
            "concern": concern,
        },
    )
