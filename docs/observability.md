# Observability Design: OpenTelemetry + Prometheus + Grafana + Loki

**Document Version:** 1.0
**Created:** 2026-01-12
**Status:** Design Complete - Ready for Implementation

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Overview](#architecture-overview)
3. [Infrastructure Components](#infrastructure-components)
4. [Instrumentation Strategy](#instrumentation-strategy)
5. [Metrics Catalog](#metrics-catalog)
6. [Tracing Design](#tracing-design)
7. [Logging Architecture](#logging-architecture)
8. [LLM Cost & Token Tracking](#llm-cost--token-tracking)
9. [Dashboard Specifications](#dashboard-specifications)
10. [Alerting Rules](#alerting-rules)
11. [MCP Host Observability](#mcp-host-observability)
12. [Implementation Plan](#implementation-plan)
13. [Configuration Reference](#configuration-reference)

---

## Executive Summary

### Goal

Implement comprehensive observability for the Brain assistant using the LGTM stack (Loki, Grafana, Tempo/OTel, Mimir/Prometheus), enabling:

1. **Performance monitoring** - Latency, throughput, and error rates across all components
2. **LLM cost tracking** - Token usage, API costs, and budget monitoring via LiteLLM callbacks
3. **Distributed tracing** - End-to-end request flow from Signal → Agent → LLM → Obsidian
4. **Centralized logging** - Structured logs aggregated in Loki with Grafana exploration
5. **Resource monitoring** - Container CPU, memory, and service health
6. **MCP Host visibility** - Protocol-level metrics for the upcoming MCP implementation

### Design Principles

| Principle | Implementation |
|-----------|----------------|
| **Privacy-first** | All data stays local; no external telemetry services |
| **Low overhead** | Sampling and efficient exporters to minimize performance impact |
| **Developer-friendly** | Pre-built dashboards and simple query patterns |
| **Extensible** | Easy to add new metrics/traces as features grow |

### Stack Selection

```
┌─────────────────────────────────────────────────────────────────┐
│                        GRAFANA (UI)                              │
│        Dashboards • Explore • Alerts • Unified Interface         │
└─────────────────────────┬───────────────────────────────────────┘
                          │ Query
        ┌─────────────────┼─────────────────┐
        ↓                 ↓                 ↓
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│  PROMETHEUS   │ │     LOKI      │ │  OTEL (Tempo) │
│   Metrics     │ │     Logs      │ │    Traces     │
└───────┬───────┘ └───────┬───────┘ └───────┬───────┘
        │                 │                 │
        └─────────────────┼─────────────────┘
                          │ OTLP / Scrape
                          ↓
                ┌─────────────────────┐
                │   OTEL COLLECTOR    │
                │  Receive • Process  │
                │  Export • Transform │
                └─────────────────────┘
                          ↑
        ┌─────────────────┼─────────────────┐
        │                 │                 │
   ┌────┴────┐      ┌────┴────┐      ┌────┴────┐
   │  Agent  │      │  MCP    │      │ Services │
   │ (Python)│      │  Host   │      │ (Docker) │
   └─────────┘      └─────────┘      └──────────┘
```

---

## Architecture Overview

### Current State (Before)

```
Brain Services
├── agent        → logs to file + stdout
├── postgres     → internal stats only
├── qdrant       → /metrics endpoint (unused)
├── redis        → INFO command only
└── signal-api   → basic logs
```

### Target State (After)

```
Brain Services + Observability Stack
├── agent           → OTLP traces/metrics + Loki logs
├── postgres        → postgres_exporter metrics
├── qdrant          → native /metrics scraped
├── redis           → redis_exporter metrics
├── signal-api      → custom metrics via agent
├── otel-collector  → central telemetry hub
├── prometheus      → metrics storage + queries
├── loki            → log aggregation
├── promtail        → log shipping
└── grafana         → visualization + alerts
```

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DATA COLLECTION                                 │
└─────────────────────────────────────────────────────────────────────────────┘

1. TRACES (OTLP)
   Agent (Python) ──OTLP──→ OTel Collector ──→ Tempo/Jaeger (optional)
        │                         │
        └── litellm callback      └── Export to Prometheus (span metrics)

2. METRICS (Prometheus)
   Agent ──────────┐
   Postgres ───────┼── /metrics ──→ Prometheus ──→ Grafana
   Qdrant ─────────┤
   Redis ──────────┤
   OTel Collector ─┘

3. LOGS (Loki)
   Agent stdout ───┐
   Postgres logs ──┼── Promtail ──→ Loki ──→ Grafana
   All containers ─┘
```

---

## Infrastructure Components

### New Docker Services

```yaml
# docker-compose.observability.yml - Extend main compose

services:
  # ============================================
  # OpenTelemetry Collector - Central Hub
  # ============================================
  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.96.0
    container_name: brain-otel-collector
    command: ["--config=/etc/otel-collector-config.yaml"]
    volumes:
      - ./config/otel-collector-config.yaml:/etc/otel-collector-config.yaml:ro
    ports:
      - "4317:4317"   # OTLP gRPC
      - "4318:4318"   # OTLP HTTP
      - "8888:8888"   # Prometheus metrics (self)
      - "8889:8889"   # Prometheus exporter (for collected metrics)
    restart: unless-stopped
    depends_on:
      - prometheus
      - loki

  # ============================================
  # Prometheus - Metrics Storage
  # ============================================
  prometheus:
    image: prom/prometheus:v2.50.1
    container_name: brain-prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=30d'
      - '--web.enable-lifecycle'
      - '--web.enable-remote-write-receiver'
    volumes:
      - ./config/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./config/prometheus-rules.yml:/etc/prometheus/rules.yml:ro
      - ./data/prometheus:/prometheus
    ports:
      - "9090:9090"
    restart: unless-stopped

  # ============================================
  # Loki - Log Aggregation
  # ============================================
  loki:
    image: grafana/loki:2.9.4
    container_name: brain-loki
    command: -config.file=/etc/loki/loki-config.yaml
    volumes:
      - ./config/loki-config.yaml:/etc/loki/loki-config.yaml:ro
      - ./data/loki:/loki
    ports:
      - "3100:3100"
    restart: unless-stopped

  # ============================================
  # Promtail - Log Shipper
  # ============================================
  promtail:
    image: grafana/promtail:2.9.4
    container_name: brain-promtail
    command: -config.file=/etc/promtail/promtail-config.yaml
    volumes:
      - ./config/promtail-config.yaml:/etc/promtail/promtail-config.yaml:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./logs:/var/log/brain:ro
    depends_on:
      - loki
    restart: unless-stopped

  # ============================================
  # Grafana - Visualization
  # ============================================
  grafana:
    image: grafana/grafana:10.3.3
    container_name: brain-grafana
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD:-brain}
      - GF_USERS_ALLOW_SIGN_UP=false
      - GF_AUTH_ANONYMOUS_ENABLED=true
      - GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer
    volumes:
      - ./config/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./config/grafana/dashboards:/var/lib/grafana/dashboards:ro
      - ./data/grafana:/var/lib/grafana
    ports:
      - "3000:3000"
    depends_on:
      - prometheus
      - loki
    restart: unless-stopped

  # ============================================
  # Exporters - Service Metrics
  # ============================================
  postgres-exporter:
    image: prometheuscommunity/postgres-exporter:v0.15.0
    container_name: brain-postgres-exporter
    environment:
      DATA_SOURCE_NAME: "postgresql://brain:${POSTGRES_PASSWORD}@postgres:5432/brain?sslmode=disable"
    ports:
      - "9187:9187"
    depends_on:
      - postgres
    restart: unless-stopped

  redis-exporter:
    image: oliver006/redis_exporter:v1.58.0
    container_name: brain-redis-exporter
    environment:
      REDIS_ADDR: "redis://redis:6379"
    ports:
      - "9121:9121"
    depends_on:
      - redis
    restart: unless-stopped
```

### Resource Estimates

| Service | Memory | CPU | Disk (30d) |
|---------|--------|-----|------------|
| otel-collector | 128MB | 0.1 | - |
| prometheus | 512MB | 0.2 | ~2GB |
| loki | 256MB | 0.1 | ~1GB |
| promtail | 64MB | 0.05 | - |
| grafana | 256MB | 0.1 | ~100MB |
| postgres-exporter | 32MB | 0.01 | - |
| redis-exporter | 32MB | 0.01 | - |
| **Total** | **~1.3GB** | **~0.6** | **~3GB** |

---

## Instrumentation Strategy

### Python Agent Instrumentation

```python
# src/observability.py - Core observability module

import os
from functools import wraps
from typing import Any, Callable
import time
import logging

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentation
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION

logger = logging.getLogger(__name__)


def setup_observability(
    service_name: str = "brain-agent",
    service_version: str = "1.0.0",
    otlp_endpoint: str = "http://otel-collector:4317",
) -> tuple[trace.Tracer, metrics.Meter]:
    """Initialize OpenTelemetry instrumentation.

    Returns:
        Tuple of (tracer, meter) for manual instrumentation
    """
    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_VERSION: service_version,
        "deployment.environment": os.getenv("ENVIRONMENT", "development"),
    })

    # --- Tracing Setup ---
    tracer_provider = TracerProvider(resource=resource)

    otlp_span_exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint,
        insecure=True,
    )
    tracer_provider.add_span_processor(
        BatchSpanProcessor(otlp_span_exporter)
    )
    trace.set_tracer_provider(tracer_provider)

    # --- Metrics Setup ---
    otlp_metric_exporter = OTLPMetricExporter(
        endpoint=otlp_endpoint,
        insecure=True,
    )
    metric_reader = PeriodicExportingMetricReader(
        otlp_metric_exporter,
        export_interval_millis=30000,  # 30s
    )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
    )
    metrics.set_meter_provider(meter_provider)

    # --- Auto-instrumentation ---
    HTTPXClientInstrumentation().instrument()

    logger.info(f"Observability initialized: endpoint={otlp_endpoint}")

    return (
        trace.get_tracer(service_name),
        metrics.get_meter(service_name),
    )


# --- Metrics Instances ---
# These will be initialized by setup_observability() and used throughout

class BrainMetrics:
    """Centralized metrics for the Brain agent."""

    def __init__(self, meter: metrics.Meter):
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


# --- Decorators for easy instrumentation ---

def traced(name: str = None, attributes: dict = None):
    """Decorator to add tracing to a function."""
    def decorator(func: Callable) -> Callable:
        span_name = name or func.__name__

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for k, v in attributes.items():
                        span.set_attribute(k, v)
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(trace.StatusCode.ERROR, str(e))
                    raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for k, v in attributes.items():
                        span.set_attribute(k, v)
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(trace.StatusCode.ERROR, str(e))
                    raise

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def timed(metric_histogram):
    """Decorator to record function duration to a histogram."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                metric_histogram.record(duration_ms)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                metric_histogram.record(duration_ms)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
```

### LiteLLM Callback Integration

```python
# src/observability_litellm.py - LiteLLM callback for token/cost tracking

import litellm
from litellm.integrations.custom_logger import CustomLogger
from opentelemetry import trace, metrics
from typing import Any
import logging

logger = logging.getLogger(__name__)


class BrainLiteLLMCallback(CustomLogger):
    """Custom LiteLLM callback for observability integration.

    Captures:
    - Token counts (input/output/total)
    - Cost estimates
    - Model usage
    - Latency metrics
    - Error tracking
    """

    def __init__(self, brain_metrics: 'BrainMetrics'):
        self.metrics = brain_metrics
        self.tracer = trace.get_tracer(__name__)

    def log_pre_api_call(self, model: str, messages: list, kwargs: dict):
        """Called before LLM API request."""
        span = trace.get_current_span()
        span.set_attribute("llm.model", model)
        span.set_attribute("llm.messages_count", len(messages))

    def log_success_event(self, kwargs: dict, response_obj: Any, start_time, end_time):
        """Called after successful LLM API response."""
        try:
            model = kwargs.get("model", "unknown")

            # Extract usage from response
            usage = getattr(response_obj, "usage", None)
            if usage:
                input_tokens = getattr(usage, "prompt_tokens", 0)
                output_tokens = getattr(usage, "completion_tokens", 0)
                total_tokens = getattr(usage, "total_tokens", 0)

                # Record token metrics
                self.metrics.llm_tokens_input.add(
                    input_tokens,
                    {"model": model}
                )
                self.metrics.llm_tokens_output.add(
                    output_tokens,
                    {"model": model}
                )

                # Calculate cost using LiteLLM's cost calculator
                try:
                    cost = litellm.completion_cost(
                        model=model,
                        prompt_tokens=input_tokens,
                        completion_tokens=output_tokens,
                    )
                    self.metrics.llm_cost.add(
                        cost,
                        {"model": model}
                    )

                    # Add to span
                    span = trace.get_current_span()
                    span.set_attribute("llm.tokens.input", input_tokens)
                    span.set_attribute("llm.tokens.output", output_tokens)
                    span.set_attribute("llm.tokens.total", total_tokens)
                    span.set_attribute("llm.cost_usd", cost)

                    logger.debug(
                        f"LLM call: model={model} "
                        f"tokens={total_tokens} cost=${cost:.6f}"
                    )
                except Exception as e:
                    logger.warning(f"Could not calculate cost: {e}")

            # Record latency
            latency_ms = (end_time - start_time).total_seconds() * 1000
            self.metrics.llm_latency.record(latency_ms, {"model": model})
            self.metrics.llm_requests.add(1, {"model": model, "status": "success"})

        except Exception as e:
            logger.error(f"Error in LiteLLM success callback: {e}")

    def log_failure_event(self, kwargs: dict, response_obj: Any, start_time, end_time):
        """Called after failed LLM API request."""
        model = kwargs.get("model", "unknown")
        error_type = type(response_obj).__name__ if response_obj else "unknown"

        self.metrics.llm_requests.add(
            1,
            {"model": model, "status": "error", "error_type": error_type}
        )

        span = trace.get_current_span()
        span.set_attribute("llm.error", True)
        span.set_attribute("llm.error_type", error_type)


def setup_litellm_observability(brain_metrics: 'BrainMetrics'):
    """Configure LiteLLM with observability callbacks."""

    # Add our custom callback
    callback = BrainLiteLLMCallback(brain_metrics)
    litellm.callbacks = [callback]

    # Also enable built-in OTEL if desired (optional, for span export)
    # litellm.callbacks.append("otel")

    # Enable cost tracking
    litellm.success_callback = [callback.log_success_event]
    litellm.failure_callback = [callback.log_failure_event]

    logger.info("LiteLLM observability configured")
```

---

## Metrics Catalog

### Agent Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `brain.messages.received` | Counter | `channel` | Messages received (signal, test, etc.) |
| `brain.messages.processed` | Counter | `channel`, `status` | Messages processed |
| `brain.messages.processing_duration` | Histogram | `channel` | E2E processing time |

### LLM Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `brain.llm.requests` | Counter | `model`, `status` | LLM API calls |
| `brain.llm.tokens.input` | Counter | `model` | Input tokens consumed |
| `brain.llm.tokens.output` | Counter | `model` | Output tokens generated |
| `brain.llm.cost` | Counter | `model` | API cost in USD |
| `brain.llm.latency` | Histogram | `model` | Request latency ms |
| `brain.llm.errors` | Counter | `model`, `error_type` | API errors |

### Tool Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `brain.tools.invocations` | Counter | `tool`, `status` | Tool calls |
| `brain.tools.errors` | Counter | `tool`, `error_type` | Tool failures |
| `brain.tools.duration` | Histogram | `tool` | Execution time ms |

### Signal Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `brain.signal.polls` | Counter | `status` | Poll attempts |
| `brain.signal.poll_errors` | Counter | `error_type` | Poll failures |
| `brain.signal.messages_sent` | Counter | `status` | Outbound messages |
| `brain.signal.latency` | Histogram | `operation` | API latency |

### Obsidian Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `brain.obsidian.requests` | Counter | `operation`, `status` | API requests |
| `brain.obsidian.errors` | Counter | `operation`, `error_type` | API errors |
| `brain.obsidian.latency` | Histogram | `operation` | Latency ms |

### MCP Host Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `brain.mcp.connections` | UpDownCounter | `transport` | Active connections |
| `brain.mcp.messages` | Counter | `type`, `direction` | Protocol messages |
| `brain.mcp.tool_calls` | Counter | `tool`, `status` | Tool invocations |
| `brain.mcp.latency` | Histogram | `operation` | Protocol latency |

### Resource Metrics (from exporters)

| Metric | Source | Description |
|--------|--------|-------------|
| `pg_stat_*` | postgres-exporter | PostgreSQL stats |
| `redis_*` | redis-exporter | Redis stats |
| `qdrant_*` | Qdrant native | Vector DB stats |
| `container_*` | cAdvisor (optional) | Container resources |

---

## Tracing Design

### Trace Hierarchy

```
Signal Message Received
├── Authorize Sender
├── Log to Conversation Memory
│   └── Obsidian API: append_to_note
├── Process Message
│   └── Pydantic AI Agent Run
│       ├── LLM Request (Claude)
│       │   ├── Token counting
│       │   └── Cost calculation
│       ├── Tool: search_notes (optional)
│       │   └── Obsidian API: search
│       ├── Tool: read_note (optional)
│       │   └── Obsidian API: get_note
│       └── Tool: create_note (optional)
│           └── Obsidian API: create_note
├── Log Response to Memory
│   └── Obsidian API: append_to_note
├── Send Signal Reply
│   └── Signal API: send_message
└── Log Action to Database
    └── PostgreSQL: INSERT action_logs
```

### Span Attributes

| Span | Key Attributes |
|------|----------------|
| `signal.receive` | `signal.sender`, `signal.message_length` |
| `agent.process` | `user`, `channel`, `message_preview` |
| `llm.request` | `llm.model`, `llm.tokens.*`, `llm.cost_usd` |
| `tool.*` | `tool.name`, `tool.args`, `tool.result_length` |
| `obsidian.*` | `obsidian.operation`, `obsidian.path` |
| `signal.send` | `signal.recipient`, `signal.message_length` |

### Trace Context Propagation

```python
# Propagate trace context through async operations

from opentelemetry import trace
from opentelemetry.propagate import inject, extract

async def handle_signal_message(signal_msg: SignalMessage, ...):
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("signal.message_handler") as span:
        span.set_attribute("signal.sender", signal_msg.sender)
        span.set_attribute("signal.timestamp", signal_msg.timestamp.isoformat())

        # All downstream operations inherit this trace context
        await memory.log_message(...)
        response = await process_message(...)
        await signal_client.send_message(...)
```

---

## Logging Architecture

### Structured Logging Format

```python
# Enhance existing logging with structured output

import json
import logging
from pythonjsonlogger import jsonlogger

class BrainJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter with Brain-specific fields."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)

        # Add trace context
        span = trace.get_current_span()
        if span:
            ctx = span.get_span_context()
            log_record['trace_id'] = format(ctx.trace_id, '032x')
            log_record['span_id'] = format(ctx.span_id, '016x')

        # Standardize timestamp
        log_record['timestamp'] = datetime.utcnow().isoformat()
        log_record['service'] = 'brain-agent'


def setup_logging():
    """Configure structured JSON logging."""
    handler = logging.StreamHandler()
    handler.setFormatter(BrainJsonFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s'
    ))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
```

### Log Labels for Loki

```yaml
# Promtail will add these labels for querying

Labels:
  - service: brain-agent | brain-signal | brain-postgres
  - level: DEBUG | INFO | WARNING | ERROR
  - component: agent | signal | obsidian | llm | tools
  - channel: signal | test
```

### Example Log Queries (LogQL)

```logql
# All errors in last hour
{service="brain-agent"} |= "ERROR" | json

# LLM requests with cost
{service="brain-agent", component="llm"} | json | cost > 0

# Signal message flow (with trace correlation)
{service="brain-agent"} | json | trace_id="abc123..."

# Tool failures
{service="brain-agent", component="tools"} |= "error" | json

# High latency operations
{service="brain-agent"} | json | duration_ms > 5000
```

---

## LLM Cost & Token Tracking

### LiteLLM Integration Details

LiteLLM provides built-in cost tracking via `model_prices_and_context_window.json`:

```python
# Example: Get cost for a completion

import litellm

# Automatic cost calculation
response = await litellm.acompletion(
    model="anthropic/claude-sonnet-4-20250514",
    messages=[{"role": "user", "content": "Hello"}],
)

# Access usage
usage = response.usage
print(f"Input tokens: {usage.prompt_tokens}")
print(f"Output tokens: {usage.completion_tokens}")

# Calculate cost
cost = litellm.completion_cost(
    model="anthropic/claude-sonnet-4-20250514",
    prompt_tokens=usage.prompt_tokens,
    completion_tokens=usage.completion_tokens,
)
print(f"Cost: ${cost:.6f}")
```

### Cost Dashboard Queries

```promql
# Total cost today
sum(increase(brain_llm_cost[24h]))

# Cost by model
sum by (model) (increase(brain_llm_cost[24h]))

# Average cost per message
sum(increase(brain_llm_cost[24h])) / sum(increase(brain_messages_processed[24h]))

# Token efficiency (output/input ratio)
sum(rate(brain_llm_tokens_output[1h])) / sum(rate(brain_llm_tokens_input[1h]))

# Projected monthly cost
sum(rate(brain_llm_cost[24h])) * 60 * 60 * 24 * 30
```

### Budget Alerting

```yaml
# prometheus-rules.yml

groups:
  - name: llm-cost-alerts
    rules:
      - alert: HighLLMSpend
        expr: sum(increase(brain_llm_cost[24h])) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "LLM spend exceeded $10 in 24h"
          description: "Current 24h spend: ${{ $value | printf \"%.2f\" }}"

      - alert: LLMCostSpike
        expr: sum(rate(brain_llm_cost[5m])) > sum(rate(brain_llm_cost[1h]))  * 3
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "LLM cost spiking (3x normal)"
```

---

## Dashboard Specifications

### Dashboard 1: Brain Overview

**Purpose:** High-level health and activity summary

**Panels:**
1. **Messages Today** - Single stat, `sum(increase(brain_messages_processed[24h]))`
2. **LLM Cost Today** - Single stat with gauge, `sum(increase(brain_llm_cost[24h]))`
3. **Active Services** - Status grid (up/down for each service)
4. **Message Rate** - Time series, `rate(brain_messages_processed[5m])`
5. **Error Rate** - Time series, `sum(rate(brain_*_errors[5m]))`
6. **Latency P95** - Time series, `histogram_quantile(0.95, brain_messages_processing_duration)`

### Dashboard 2: LLM Analytics

**Purpose:** Token usage, costs, and model performance

**Panels:**
1. **Token Usage** - Stacked area (input vs output by model)
2. **Cost Breakdown** - Pie chart by model
3. **Cost Over Time** - Time series with daily aggregation
4. **Latency by Model** - Heatmap
5. **Request Success Rate** - Gauge per model
6. **Token Efficiency** - output/input ratio over time
7. **Projected Monthly Cost** - Single stat with comparison

### Dashboard 3: Signal & Obsidian

**Purpose:** Integration health and performance

**Panels:**
1. **Signal Poll Status** - Success/failure ratio
2. **Signal Latency** - P50/P95/P99 time series
3. **Messages Sent/Received** - Counter time series
4. **Obsidian Operations** - Breakdown by type (search, read, create, append)
5. **Obsidian Latency** - Histogram heatmap
6. **Obsidian Errors** - Error log table (from Loki)

### Dashboard 4: MCP Host (Future)

**Purpose:** MCP protocol monitoring

**Panels:**
1. **Active Connections** - Gauge
2. **Message Rate** - By type (request/response/notification)
3. **Tool Call Distribution** - Bar chart
4. **Protocol Errors** - Time series
5. **Latency Breakdown** - By operation type

### Dashboard 5: Infrastructure

**Purpose:** Resource utilization

**Panels:**
1. **Container Memory** - Per service stacked area
2. **Container CPU** - Per service time series
3. **PostgreSQL Connections** - Active/idle pool
4. **PostgreSQL Query Performance** - From pg_stat
5. **Redis Memory** - Used vs max
6. **Redis Operations** - Commands/sec
7. **Qdrant Collections** - Vector count and memory

---

## Alerting Rules

### Critical Alerts

```yaml
groups:
  - name: brain-critical
    rules:
      - alert: AgentDown
        expr: up{job="brain-agent"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Brain agent is down"

      - alert: SignalAPIDown
        expr: up{job="brain-signal"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Signal API is unreachable"

      - alert: PostgresDown
        expr: pg_up == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "PostgreSQL is down"
```

### Warning Alerts

```yaml
groups:
  - name: brain-warnings
    rules:
      - alert: HighErrorRate
        expr: |
          sum(rate(brain_messages_processed{status="error"}[5m]))
          / sum(rate(brain_messages_processed[5m])) > 0.1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Error rate above 10%"

      - alert: HighLatency
        expr: |
          histogram_quantile(0.95, rate(brain_messages_processing_duration_bucket[5m])) > 30000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "P95 latency above 30s"

      - alert: ObsidianAPIErrors
        expr: rate(brain_obsidian_errors[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Obsidian API errors detected"
```

---

## MCP Host Observability

### Instrumentation Points

When Codex implements the MCP Host, these observability hooks should be added:

```python
# Suggested MCP Host instrumentation

class MCPHostObservability:
    """Observability wrapper for MCP Host operations."""

    def __init__(self, metrics: BrainMetrics, tracer: trace.Tracer):
        self.metrics = metrics
        self.tracer = tracer

    async def on_connection_opened(self, transport: str, client_id: str):
        """Track new MCP connections."""
        self.metrics.mcp_connections.add(1, {"transport": transport})

    async def on_connection_closed(self, transport: str, client_id: str):
        """Track closed MCP connections."""
        self.metrics.mcp_connections.add(-1, {"transport": transport})

    async def on_message_received(self, message_type: str, method: str = None):
        """Track incoming MCP messages."""
        self.metrics.mcp_messages.add(1, {
            "type": message_type,
            "direction": "inbound",
            "method": method or "unknown",
        })

    async def on_message_sent(self, message_type: str, method: str = None):
        """Track outgoing MCP messages."""
        self.metrics.mcp_messages.add(1, {
            "type": message_type,
            "direction": "outbound",
            "method": method or "unknown",
        })

    async def on_tool_call(self, tool_name: str, duration_ms: float, success: bool):
        """Track MCP tool invocations."""
        self.metrics.mcp_tool_calls.add(1, {
            "tool": tool_name,
            "status": "success" if success else "error",
        })
        self.metrics.mcp_latency.record(duration_ms, {"operation": f"tool.{tool_name}"})


# Trace wrapper for MCP handlers
@traced("mcp.handle_request")
async def handle_mcp_request(request: MCPRequest) -> MCPResponse:
    span = trace.get_current_span()
    span.set_attribute("mcp.method", request.method)
    span.set_attribute("mcp.id", request.id)
    # ... handle request
```

### MCP-Specific Metrics

| Metric | Description |
|--------|-------------|
| `brain.mcp.connections` | Active connection count by transport |
| `brain.mcp.messages` | Message count by type/direction |
| `brain.mcp.tool_calls` | Tool invocation count by tool/status |
| `brain.mcp.resource_reads` | Resource read count |
| `brain.mcp.prompt_completions` | Prompt completions served |
| `brain.mcp.latency` | Operation latency histogram |

---

## Implementation Plan

### Phase 1: Infrastructure (1-2 hours)

1. Create `docker-compose.observability.yml`
2. Create configuration files:
   - `config/otel-collector-config.yaml`
   - `config/prometheus.yml`
   - `config/loki-config.yaml`
   - `config/promtail-config.yaml`
   - `config/grafana/provisioning/datasources/datasources.yaml`
3. Add data directories: `data/prometheus`, `data/loki`, `data/grafana`
4. Test stack startup: `docker compose -f docker-compose.yml -f docker-compose.observability.yml up`

### Phase 2: Agent Instrumentation (2-3 hours)

1. Add Python dependencies to `pyproject.toml`:
   ```toml
   opentelemetry-api = "^1.22.0"
   opentelemetry-sdk = "^1.22.0"
   opentelemetry-exporter-otlp = "^1.22.0"
   opentelemetry-instrumentation-httpx = "^0.43b0"
   opentelemetry-instrumentation-sqlalchemy = "^0.43b0"
   python-json-logger = "^2.0.7"
   ```
2. Create `src/observability.py` with setup and metrics
3. Create `src/observability_litellm.py` with LiteLLM callback
4. Update `src/agent.py` to initialize observability
5. Instrument key functions with `@traced` and metrics

### Phase 3: Dashboard Setup (1-2 hours)

1. Create Grafana dashboard JSON files:
   - `config/grafana/dashboards/overview.json`
   - `config/grafana/dashboards/llm-analytics.json`
   - `config/grafana/dashboards/integrations.json`
   - `config/grafana/dashboards/infrastructure.json`
2. Configure dashboard provisioning
3. Import and verify dashboards

### Phase 4: Alerting (30 minutes)

1. Create `config/prometheus-rules.yml`
2. Configure alert manager (optional) or Grafana alerting
3. Test alert conditions

### Phase 5: MCP Host Integration (When Ready)

1. Add observability hooks to MCP Host implementation
2. Create MCP-specific dashboard
3. Add MCP alerts

---

## Configuration Reference

### OTel Collector Config

```yaml
# config/otel-collector-config.yaml

receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 10s
    send_batch_size: 1024
  memory_limiter:
    check_interval: 1s
    limit_mib: 128

exporters:
  prometheus:
    endpoint: "0.0.0.0:8889"
    namespace: brain
  loki:
    endpoint: http://loki:3100/loki/api/v1/push
  logging:
    loglevel: debug

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [logging]  # Add tempo exporter if using Tempo
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [prometheus]
    logs:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [loki]
```

### Prometheus Config

```yaml
# config/prometheus.yml

global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - /etc/prometheus/rules.yml

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'otel-collector'
    static_configs:
      - targets: ['otel-collector:8889']

  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres-exporter:9187']

  - job_name: 'redis'
    static_configs:
      - targets: ['redis-exporter:9121']

  - job_name: 'qdrant'
    static_configs:
      - targets: ['qdrant:6333']
    metrics_path: /metrics
```

### Loki Config

```yaml
# config/loki-config.yaml

auth_enabled: false

server:
  http_listen_port: 3100

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

limits_config:
  retention_period: 30d
```

### Promtail Config

```yaml
# config/promtail-config.yaml

server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: docker
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 5s
    relabel_configs:
      - source_labels: ['__meta_docker_container_name']
        regex: '/(.*)'
        target_label: 'container'
      - source_labels: ['__meta_docker_container_label_com_docker_compose_service']
        target_label: 'service'
    pipeline_stages:
      - json:
          expressions:
            level: level
            msg: message
            trace_id: trace_id
      - labels:
          level:
          trace_id:

  - job_name: brain-logs
    static_configs:
      - targets:
          - localhost
        labels:
          job: brain-agent
          __path__: /var/log/brain/*.log
    pipeline_stages:
      - json:
          expressions:
            level: level
            component: name
            trace_id: trace_id
      - labels:
          level:
          component:
          trace_id:
```

### Grafana Datasource Provisioning

```yaml
# config/grafana/provisioning/datasources/datasources.yaml

apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false

  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    editable: false
    jsonData:
      derivedFields:
        - datasourceUid: prometheus
          matcherRegex: "trace_id=(\\w+)"
          name: TraceID
          url: "$${__value.raw}"
```

---

## Quick Start

```bash
# 1. Start observability stack
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d

# 2. Verify services
curl http://localhost:9090/-/healthy  # Prometheus
curl http://localhost:3100/ready      # Loki
curl http://localhost:3000/api/health # Grafana

# 3. Access Grafana
open http://localhost:3000
# Login: admin / brain (or GRAFANA_PASSWORD env var)

# 4. Import dashboards (if not auto-provisioned)
# Go to Dashboards > Import > Upload JSON
```

---

## Sources

- [LiteLLM OpenTelemetry Integration](https://docs.litellm.ai/docs/observability/opentelemetry_integration)
- [LiteLLM Logging & Callbacks](https://docs.litellm.ai/docs/proxy/logging)
- [OpenTelemetry LLM Observability](https://opentelemetry.io/blog/2024/llm-observability/)
- [Langfuse Token & Cost Tracking](https://langfuse.com/docs/observability/features/token-and-cost-tracking)
- [LLM Cost Tracker (Self-hosted)](https://github.com/danieleschmidt/llm-cost-tracker)
