"""Unit tests for public API metrics concern behavior."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.brain_shared.logging.public_api import (
    CompletionContext,
    InvocationContext,
    PublicApiMetricsConcern,
)


class _FakeCounter:
    """In-memory fake counter recording each add call."""

    def __init__(self) -> None:
        self.calls: list[tuple[int | float, dict[str, str]]] = []

    def add(self, amount: int | float, attributes: dict[str, str]) -> None:
        self.calls.append((amount, dict(attributes)))


class _FakeHistogram:
    """In-memory fake histogram recording each sample."""

    def __init__(self) -> None:
        self.samples: list[tuple[float, dict[str, str]]] = []

    def record(self, amount: float, attributes: dict[str, str]) -> None:
        self.samples.append((amount, dict(attributes)))


def _concern() -> tuple[PublicApiMetricsConcern, _FakeCounter, _FakeHistogram]:
    calls = _FakeCounter()
    durations = _FakeHistogram()
    errors = _FakeCounter()
    qdrant_calls = _FakeCounter()
    qdrant_durations = _FakeHistogram()
    return (
        PublicApiMetricsConcern(
            public_api_calls_total=calls,
            public_api_duration_ms=durations,
            public_api_errors_total=errors,
            qdrant_ops_total=qdrant_calls,
            qdrant_op_duration_ms=qdrant_durations,
        ),
        errors,
        qdrant_durations,
    )


def test_metrics_concern_emits_calls_and_duration_for_success() -> None:
    """Successful completion should emit core counters/histograms only."""
    calls = _FakeCounter()
    durations = _FakeHistogram()
    errors = _FakeCounter()
    qdrant_calls = _FakeCounter()
    qdrant_durations = _FakeHistogram()
    concern = PublicApiMetricsConcern(
        public_api_calls_total=calls,
        public_api_duration_ms=durations,
        public_api_errors_total=errors,
        qdrant_ops_total=qdrant_calls,
        qdrant_op_duration_ms=qdrant_durations,
    )
    context = CompletionContext(
        invocation=InvocationContext(
            component_id="service_embedding_authority",
            api_name="upsert_source",
            trace_id="t",
            envelope_id="e",
            principal="operator",
            references={},
        ),
        success=True,
        duration_ms=12.5,
        errors=[],
        error_categories=[],
    )

    concern.on_completion(context)

    assert calls.calls == [
        (
            1,
            {
                "component_id": "service_embedding_authority",
                "api_name": "upsert_source",
                "outcome": "success",
            },
        )
    ]
    assert durations.samples == [
        (
            12.5,
            {
                "component_id": "service_embedding_authority",
                "api_name": "upsert_source",
                "outcome": "success",
            },
        )
    ]
    assert errors.calls == []
    assert qdrant_calls.calls == []
    assert qdrant_durations.samples == []


def test_metrics_concern_emits_failure_categories_and_qdrant_metrics() -> None:
    """Failed Qdrant completions should emit error and Qdrant metric series."""
    calls = _FakeCounter()
    durations = _FakeHistogram()
    errors = _FakeCounter()
    qdrant_calls = _FakeCounter()
    qdrant_durations = _FakeHistogram()
    concern = PublicApiMetricsConcern(
        public_api_calls_total=calls,
        public_api_duration_ms=durations,
        public_api_errors_total=errors,
        qdrant_ops_total=qdrant_calls,
        qdrant_op_duration_ms=qdrant_durations,
    )
    context = CompletionContext(
        invocation=InvocationContext(
            component_id="substrate_qdrant",
            api_name="upsert_point",
            trace_id=None,
            envelope_id=None,
            principal=None,
            references={"point_id": "p"},
        ),
        success=False,
        duration_ms=7.0,
        errors=["DEPENDENCY_UNAVAILABLE: qdrant unavailable"],
        error_categories=["dependency"],
    )

    concern.on_completion(context)

    assert qdrant_calls.calls == [
        (1, {"api_name": "upsert_point", "outcome": "failure"})
    ]
    assert qdrant_durations.samples == [
        (7.0, {"api_name": "upsert_point", "outcome": "failure"})
    ]
    assert errors.calls == [
        (
            1,
            {
                "component_id": "substrate_qdrant",
                "api_name": "upsert_point",
                "error_category": "dependency",
            },
        )
    ]
