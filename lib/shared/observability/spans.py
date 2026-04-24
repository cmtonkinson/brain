"""Span-attribute helpers shared by adapters and services using OTel tracing."""

from __future__ import annotations


def set_span_attributes(span: object, attributes: dict[str, object | None]) -> None:
    """Attach non-empty OTel-compatible attributes to one supplied span.

    Skips ``None``, empty string, empty dict, and empty list values. Tolerates
    duck-typed spans that may not expose ``set_attribute`` (e.g., no-op spans).
    """
    set_attribute = getattr(span, "set_attribute", None)
    if not callable(set_attribute):
        return
    for key, value in attributes.items():
        if value in (None, "", {}, []):
            continue
        set_attribute(key, value)


def set_current_span_attributes(attributes: dict[str, object | None]) -> None:
    """Attach attributes to the active OTel span when tracing is active.

    No-ops when OpenTelemetry is not installed or no span is current. Skips
    entries whose value is ``None`` or the empty string.
    """
    try:
        from opentelemetry import trace
    except ImportError:
        return
    span = trace.get_current_span()
    if span is None:
        return
    for key, value in attributes.items():
        if value in (None, ""):
            continue
        span.set_attribute(key, value)
