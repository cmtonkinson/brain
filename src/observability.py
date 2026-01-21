"""
Observability module for the Brain agent.

Provides OpenTelemetry-based tracing, metrics, and logging.
See docs/observability.md for full documentation.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

if TYPE_CHECKING:
    from opentelemetry.metrics import Meter
    from opentelemetry.trace import Tracer

logger = logging.getLogger(__name__)

# Type variable for decorator
F = TypeVar("F", bound=Callable[..., Any])

# Global instances (set by setup_observability)
_tracer: Tracer | None = None
_meter: Meter | None = None
_metrics: BrainMetrics | None = None


class BrainMetrics:
    """Centralized metrics for the Brain agent.

    All metrics use the 'brain.' prefix and are exported via OTLP to Prometheus.
    """

    def __init__(self, meter: Meter) -> None:
        """Initialize Brain metrics instruments on the provided meter."""
        # Message processing
        self.messages_received = meter.create_counter(
            "brain.messages.received",
            description="Total messages received",
            unit="1",
        )
        self.messages_processed = meter.create_counter(
            "brain.messages.processed",
            description="Total messages successfully processed",
            unit="1",
        )
        self.message_processing_duration = meter.create_histogram(
            "brain.messages.processing_duration",
            description="Message processing latency",
            unit="ms",
        )

        # LLM metrics
        self.llm_requests = meter.create_counter(
            "brain.llm.requests",
            description="Total LLM API requests",
            unit="1",
        )
        self.llm_tokens_input = meter.create_counter(
            "brain.llm.tokens.input",
            description="Total input tokens sent to LLM",
            unit="1",
        )
        self.llm_tokens_output = meter.create_counter(
            "brain.llm.tokens.output",
            description="Total output tokens received from LLM",
            unit="1",
        )
        self.llm_cost = meter.create_counter(
            "brain.llm.cost",
            description="Estimated LLM API cost in USD",
            unit="USD",
        )
        self.llm_latency = meter.create_histogram(
            "brain.llm.latency",
            description="LLM API request latency",
            unit="ms",
        )

        # Tool invocations
        self.tool_invocations = meter.create_counter(
            "brain.tools.invocations",
            description="Total tool invocations",
            unit="1",
        )
        self.tool_errors = meter.create_counter(
            "brain.tools.errors",
            description="Total tool errors",
            unit="1",
        )
        self.tool_duration = meter.create_histogram(
            "brain.tools.duration",
            description="Tool execution duration",
            unit="ms",
        )

        # Signal integration
        self.signal_polls = meter.create_counter(
            "brain.signal.polls",
            description="Signal API poll attempts",
            unit="1",
        )
        self.signal_poll_errors = meter.create_counter(
            "brain.signal.poll_errors",
            description="Signal API poll failures",
            unit="1",
        )
        self.signal_messages_sent = meter.create_counter(
            "brain.signal.messages_sent",
            description="Signal messages sent",
            unit="1",
        )
        self.signal_latency = meter.create_histogram(
            "brain.signal.latency",
            description="Signal API latency",
            unit="ms",
        )

        # Obsidian integration
        self.obsidian_requests = meter.create_counter(
            "brain.obsidian.requests",
            description="Obsidian API requests",
            unit="1",
        )
        self.obsidian_errors = meter.create_counter(
            "brain.obsidian.errors",
            description="Obsidian API errors",
            unit="1",
        )
        self.obsidian_latency = meter.create_histogram(
            "brain.obsidian.latency",
            description="Obsidian API latency",
            unit="ms",
        )

        # MCP Host (future)
        self.mcp_connections = meter.create_up_down_counter(
            "brain.mcp.connections",
            description="Active MCP connections",
            unit="1",
        )
        self.mcp_messages = meter.create_counter(
            "brain.mcp.messages",
            description="MCP protocol messages",
            unit="1",
        )
        self.mcp_tool_calls = meter.create_counter(
            "brain.mcp.tool_calls",
            description="MCP tool invocations",
            unit="1",
        )
        self.mcp_latency = meter.create_histogram(
            "brain.mcp.latency",
            description="MCP operation latency",
            unit="ms",
        )


def setup_observability(
    service_name: str = "brain-agent",
    service_version: str = "1.0.0",
    otlp_endpoint: str | None = None,
    enable_console_exporter: bool = False,
) -> tuple[Tracer, Meter, BrainMetrics]:
    """Initialize OpenTelemetry instrumentation for traces, metrics, and logs.

    Args:
        service_name: Name of the service for telemetry
        service_version: Version of the service
        otlp_endpoint: OTLP collector endpoint (defaults to OTEL_EXPORTER_OTLP_ENDPOINT env var)
        enable_console_exporter: If True, also log spans to console (for debugging)

    Returns:
        Tuple of (tracer, meter, metrics) for manual instrumentation
    """
    global _tracer, _meter, _metrics

    # Get endpoint from env if not provided
    if otlp_endpoint is None:
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")

    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            SERVICE_VERSION: service_version,
            "deployment.environment": os.getenv("ENVIRONMENT", "development"),
            "service.namespace": "brain",
        }
    )

    # --- Tracing Setup ---
    tracer_provider = TracerProvider(resource=resource)
    if otlp_endpoint:
        otlp_span_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        tracer_provider.add_span_processor(BatchSpanProcessor(otlp_span_exporter))

    if enable_console_exporter:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

        tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(tracer_provider)

    # --- Metrics Setup ---
    metric_reader = None
    if otlp_endpoint:
        otlp_metric_exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
        metric_reader = PeriodicExportingMetricReader(
            otlp_metric_exporter, export_interval_millis=30000
        )

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader] if metric_reader else [],
    )
    metrics.set_meter_provider(meter_provider)

    # --- Logging Setup ---
    logger_provider = LoggerProvider(resource=resource)
    set_logger_provider(logger_provider)

    if otlp_endpoint:
        otlp_log_exporter = OTLPLogExporter(endpoint=otlp_endpoint, insecure=True)
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(otlp_log_exporter))

    # --- Auto-instrumentation ---
    HTTPXClientInstrumentor().instrument()

    # Store global instances
    _tracer = trace.get_tracer(service_name, service_version)
    _meter = metrics.get_meter(service_name, service_version)
    _metrics = BrainMetrics(_meter)

    if otlp_endpoint:
        logger.info(f"Observability initialized: endpoint={otlp_endpoint}")
    else:
        logger.info("Observability disabled (OTEL_EXPORTER_OTLP_ENDPOINT not set)")

    return _tracer, _meter, _metrics


def configure_logging(level: str, otel_level: str) -> None:
    """Configure dual-handler logging to STDOUT and OTLP.

    Args:
        level: Logging level for stdout handler.
        otel_level: Logging level for OTLP handler.
    """
    # Convert string log levels to numeric
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    numeric_otel_level = getattr(logging, otel_level.upper(), logging.INFO)

    # The root logger must have the lowest level of all handlers
    root_level = min(numeric_level, numeric_otel_level)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(root_level)

    # 1. Console Handler (for docker logs)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(numeric_level)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    stdout_handler.setFormatter(formatter)
    root_logger.addHandler(stdout_handler)

    # 2. OTLP Handler (if endpoint is configured)
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        # The LoggerProvider is already configured in setup_observability.
        # The LoggingHandler will automatically use the global provider.
        otlp_handler = LoggingHandler(level=numeric_otel_level)
        root_logger.addHandler(otlp_handler)
        logger.info("OTLP log handler configured and added.")

    # Reduce noise from common libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("opentelemetry").setLevel(logging.WARNING)


def get_tracer() -> Tracer:
    """Get the global tracer instance."""
    if _tracer is None:
        raise RuntimeError("Observability not initialized. Call setup_observability() first.")
    return _tracer


def get_meter() -> Meter:
    """Get the global meter instance."""
    if _meter is None:
        raise RuntimeError("Observability not initialized. Call setup_observability() first.")
    return _meter


def get_metrics() -> BrainMetrics:
    """Get the global metrics instance."""
    if _metrics is None:
        raise RuntimeError("Observability not initialized. Call setup_observability() first.")
    return _metrics


# --- Decorators for easy instrumentation ---


def traced(name: str | None = None, attributes: dict[str, Any] | None = None) -> Callable[[F], F]:
    """Decorator to add tracing to a function.

    Args:
        name: Span name (defaults to function name)
        attributes: Additional span attributes

    Example:
        @traced("process_message", {"channel": "signal"})
        async def handle_message(msg):
            ...
    """

    def decorator(func: F) -> F:
        span_name = name or func.__name__

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for k, v in attributes.items():
                        span.set_attribute(k, v)
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for k, v in attributes.items():
                        span.set_attribute(k, v)
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator


def timed(
    histogram_name: str,
    labels: dict[str, str] | None = None,
) -> Callable[[F], F]:
    """Decorator to record function duration to a histogram.

    Args:
        histogram_name: Name of histogram attribute on BrainMetrics
        labels: Additional labels for the metric

    Example:
        @timed("tool_duration", {"tool": "search_notes"})
        async def search_notes(query):
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                m = get_metrics()
                histogram = getattr(m, histogram_name, None)
                if histogram:
                    histogram.record(duration_ms, labels or {})

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                m = get_metrics()
                histogram = getattr(m, histogram_name, None)
                if histogram:
                    histogram.record(duration_ms, labels or {})

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator


# --- Context managers for manual instrumentation ---


class SpanContext:
    """Context manager for creating spans with automatic error handling.

    Example:
        async with SpanContext("process_message", {"user": user_id}) as span:
            span.set_attribute("message_length", len(message))
            result = await process(message)
    """

    def __init__(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Initialize a span context with optional attributes."""
        self.name = name
        self.attributes = attributes or {}
        self.span: trace.Span | None = None

    def __enter__(self) -> trace.Span:
        """Enter a span context and attach attributes."""
        tracer = get_tracer()
        self.span = tracer.start_span(self.name)
        self.span.__enter__()
        for k, v in self.attributes.items():
            self.span.set_attribute(k, v)
        return self.span

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the span, recording errors if any."""
        if self.span:
            if exc_val:
                self.span.record_exception(exc_val)
                self.span.set_status(Status(StatusCode.ERROR, str(exc_val)))
            self.span.__exit__(exc_type, exc_val, exc_tb)

    async def __aenter__(self) -> trace.Span:
        """Async enter wrapper for compatibility with async contexts."""
        return self.__enter__()

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async exit wrapper for compatibility with async contexts."""
        self.__exit__(exc_type, exc_val, exc_tb)
