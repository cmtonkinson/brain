"""Canonical logging field names for cross-service consistency.

These constants define a stable key set for structured logs and context
propagation. Keeping names centralized prevents accidental drift between
services and future observability integrations.
"""

TIMESTAMP = "timestamp"
LEVEL = "level"
LOGGER = "logger"
MESSAGE = "message"
EVENT = "event"

# Envelope/correlation fields.
TRACE_ID = "trace_id"
ENVELOPE_ID = "envelope_id"
PARENT_ID = "parent_id"
SOURCE = "source"
PRINCIPAL = "principal"

# Public API invocation fields.
COMPONENT_ID = "component_id"
API_NAME = "api_name"
PUBLIC_API_INVOCATION_EVENT = "public_api_invocation"
PUBLIC_API_COMPLETION_EVENT = "public_api_completion"
PUBLIC_API_INSTRUMENTATION_FAILURE_EVENT = "public_api_instrumentation_failure"
SUCCESS = "success"
DURATION_MS = "duration_ms"
ERRORS = "errors"
OUTCOME = "outcome"
ERROR_CATEGORY = "error_category"
STAGE = "stage"
CONCERN = "concern"

# Future tracing compatibility fields.
OTEL_TRACE_ID = "otel_trace_id"
OTEL_SPAN_ID = "otel_span_id"

# Common service-level fields.
SERVICE = "service"
ENVIRONMENT = "environment"
