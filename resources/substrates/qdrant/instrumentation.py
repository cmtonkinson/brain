"""Qdrant-specific public API metrics concern wiring.

Lives in the Qdrant substrate package (not in ``lib.shared.logging``) so the
generic instrumentation library remains free of substrate-specific names. The
concern factory is registered with ``register_public_api_concern`` from
:mod:`resources.substrates.qdrant.boot` so it participates in every decorated
public API call without requiring per-callsite wiring.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping, Protocol

from lib.shared.logging import (
    CompletionContext,
    InvocationContext,
    PublicApiInstrumentationConcern,
)
from lib.shared.logging.fields import API_NAME, OUTCOME
from resources.substrates.qdrant.component import RESOURCE_COMPONENT_ID

_METRIC_QDRANT_OPS_TOTAL = "brain_qdrant_ops_total"
_METRIC_QDRANT_OP_DURATION_MS = "brain_qdrant_op_duration_ms"
_METER_NAME = "brain.qdrant"


class _CounterLike(Protocol):
    """Minimal counter interface used by the Qdrant metrics concern."""

    def add(self, amount: int | float, attributes: Mapping[str, str]) -> None:
        """Record one counter increment with attributes."""


class _HistogramLike(Protocol):
    """Minimal histogram interface used by the Qdrant metrics concern."""

    def record(self, amount: float, attributes: Mapping[str, str]) -> None:
        """Record one sample with attributes."""


@dataclass(frozen=True)
class QdrantPublicApiMetricsConcern:
    """Emit Qdrant-specific operation counters/histograms on completion."""

    qdrant_ops_total: _CounterLike
    qdrant_op_duration_ms: _HistogramLike
    component_id: str = str(RESOURCE_COMPONENT_ID)

    def on_invocation(self, context: InvocationContext) -> None:
        """No-op at invocation; Qdrant metrics are emitted on completion."""

    def on_completion(self, context: CompletionContext) -> None:
        """Emit Qdrant counters/histograms when the call targets this substrate."""
        if context.invocation.component_id != self.component_id:
            return
        outcome = "success" if context.success else "failure"
        attrs = {
            API_NAME: context.invocation.api_name,
            OUTCOME: outcome,
        }
        self.qdrant_ops_total.add(1, attributes=attrs)
        self.qdrant_op_duration_ms.record(context.duration_ms, attributes=attrs)


@lru_cache(maxsize=1)
def qdrant_public_api_metrics_concern_factory() -> (
    PublicApiInstrumentationConcern | None
):
    """Build the default Qdrant metrics concern when OTel is available."""
    try:
        from opentelemetry import metrics as otel_metrics
    except ImportError:
        return None
    meter = otel_metrics.get_meter(_METER_NAME)
    return QdrantPublicApiMetricsConcern(
        qdrant_ops_total=meter.create_counter(
            name=_METRIC_QDRANT_OPS_TOTAL,
            description="Count of Qdrant substrate operations by outcome.",
            unit="1",
        ),
        qdrant_op_duration_ms=meter.create_histogram(
            name=_METRIC_QDRANT_OP_DURATION_MS,
            description="Qdrant substrate operation latency in milliseconds.",
            unit="ms",
        ),
    )
