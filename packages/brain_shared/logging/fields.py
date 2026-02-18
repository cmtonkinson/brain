"""Canonical logging field names for cross-service consistency.

These constants define a stable key set for structured logs and context
propagation. Keeping names centralized prevents accidental drift between
services and future observability integrations.
"""

TIMESTAMP = "timestamp"
LEVEL = "level"
LOGGER = "logger"
MESSAGE = "message"

# Envelope/correlation fields.
TRACE_ID = "trace_id"
ENVELOPE_ID = "envelope_id"
PARENT_ID = "parent_id"
SOURCE = "source"
PRINCIPAL = "principal"

# Future tracing compatibility fields.
OTEL_TRACE_ID = "otel_trace_id"
OTEL_SPAN_ID = "otel_span_id"

# Common service-level fields.
SERVICE = "service"
ENVIRONMENT = "environment"
