"""Unit tests for public API tracing concern behavior."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.brain_shared.logging.public_api import (
    CompletionContext,
    InvocationContext,
    PublicApiTracingConcern,
)


class _FakeSpan:
    """In-memory fake span capturing attributes and lifecycle updates."""

    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}
        self.exceptions: list[Exception] = []
        self.statuses: list[object] = []

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def record_exception(self, exception: Exception) -> None:
        self.exceptions.append(exception)

    def set_status(self, status: object) -> None:
        self.statuses.append(status)


class _FakeSpanManager:
    """Fake span context manager used by the fake tracer."""

    def __init__(self, span: _FakeSpan) -> None:
        self._span = span
        self.exited = False

    def __enter__(self) -> _FakeSpan:
        return self._span

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb
        self.exited = True


class _FakeTracer:
    """Fake tracer returning tracked span context managers."""

    def __init__(self) -> None:
        self.names: list[str] = []
        self.managers: list[_FakeSpanManager] = []

    def start_as_current_span(self, name: str) -> _FakeSpanManager:
        self.names.append(name)
        manager = _FakeSpanManager(_FakeSpan())
        self.managers.append(manager)
        return manager


def test_tracing_concern_starts_and_completes_span_with_attributes() -> None:
    """Completion should set standard attributes and close span context."""
    tracer = _FakeTracer()
    concern = PublicApiTracingConcern(tracer=tracer)
    invocation = InvocationContext(
        component_id="service_embedding_authority",
        api_name="upsert_source",
        trace_id="trace-1",
        envelope_id="env-1",
        principal="operator",
        references={"source_id": "01ABC"},
    )

    concern.on_invocation(invocation)
    concern.on_completion(
        CompletionContext(
            invocation=invocation,
            success=True,
            duration_ms=12.3,
            errors=[],
            error_categories=[],
        )
    )

    assert tracer.names == ["public_api.service_embedding_authority.upsert_source"]
    manager = tracer.managers[0]
    assert manager.exited is True
    assert manager._span.attributes["component_id"] == "service_embedding_authority"
    assert manager._span.attributes["api_name"] == "upsert_source"
    assert manager._span.attributes["outcome"] == "success"
    assert manager._span.attributes["errors.count"] == 0


def test_tracing_concern_records_exception_for_failures() -> None:
    """Failed completions should record one synthetic exception on the span."""
    tracer = _FakeTracer()
    concern = PublicApiTracingConcern(tracer=tracer)
    invocation = InvocationContext(
        component_id="substrate_qdrant",
        api_name="upsert_point",
        trace_id=None,
        envelope_id=None,
        principal=None,
        references={"point_id": "p1"},
    )

    concern.on_invocation(invocation)
    concern.on_completion(
        CompletionContext(
            invocation=invocation,
            success=False,
            duration_ms=9.0,
            errors=["DEPENDENCY_UNAVAILABLE: qdrant unavailable"],
            error_categories=["dependency"],
        )
    )

    manager = tracer.managers[0]
    assert manager.exited is True
    assert manager._span.attributes["outcome"] == "failure"
    assert len(manager._span.exceptions) == 1
