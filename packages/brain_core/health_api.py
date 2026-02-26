"""gRPC adapter for Core aggregate health."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone

import grpc
from brain.shared.v1 import core_health_pb2, core_health_pb2_grpc, envelope_pb2

from packages.brain_core.health import CoreHealthResult, evaluate_core_health
from packages.brain_shared.config import BrainSettings
from packages.brain_shared.envelope import EnvelopeKind, EnvelopeMeta, new_meta


class GrpcCoreHealthService(core_health_pb2_grpc.CoreHealthServiceServicer):
    """gRPC servicer exposing aggregate Core health state."""

    def __init__(self, *, settings: BrainSettings, components: Mapping[str, object]):
        self._settings = settings
        self._components = components

    def Health(
        self,
        request: core_health_pb2.CoreHealthRequest,
        context: grpc.ServicerContext,
    ) -> core_health_pb2.CoreHealthResponse:
        del context
        result = evaluate_core_health(
            settings=self._settings,
            components=self._components,
        )
        return core_health_pb2.CoreHealthResponse(
            metadata=_meta_to_proto(_meta_from_proto(request.metadata)),
            payload=_health_to_proto(result),
            errors=[],
        )


def register_grpc(
    *,
    server: grpc.Server,
    settings: BrainSettings,
    components: Mapping[str, object],
) -> None:
    """Register CoreHealthService gRPC implementation on one server."""
    core_health_pb2_grpc.add_CoreHealthServiceServicer_to_server(
        GrpcCoreHealthService(settings=settings, components=components),
        server,
    )


def _meta_from_proto(meta: envelope_pb2.EnvelopeMeta) -> EnvelopeMeta:
    """Convert protobuf metadata into canonical envelope metadata."""
    if meta.timestamp.seconds == 0 and meta.timestamp.nanos == 0:
        return new_meta(
            kind=EnvelopeKind.RESULT,
            source="core_health",
            principal="system",
        )

    timestamp = datetime.fromtimestamp(
        meta.timestamp.seconds + (meta.timestamp.nanos / 1_000_000_000),
        tz=timezone.utc,
    )
    kind_map = {
        envelope_pb2.ENVELOPE_KIND_UNSPECIFIED: EnvelopeKind.UNSPECIFIED,
        envelope_pb2.ENVELOPE_KIND_COMMAND: EnvelopeKind.COMMAND,
        envelope_pb2.ENVELOPE_KIND_EVENT: EnvelopeKind.EVENT,
        envelope_pb2.ENVELOPE_KIND_RESULT: EnvelopeKind.RESULT,
        envelope_pb2.ENVELOPE_KIND_STREAM: EnvelopeKind.STREAM,
    }
    return EnvelopeMeta(
        envelope_id=meta.envelope_id,
        trace_id=meta.trace_id,
        parent_id=meta.parent_id,
        kind=kind_map.get(meta.kind, EnvelopeKind.RESULT),
        timestamp=timestamp,
        source=meta.source or "core_health",
        principal=meta.principal or "system",
    )


def _meta_to_proto(meta: EnvelopeMeta) -> envelope_pb2.EnvelopeMeta:
    """Convert canonical envelope metadata into protobuf shape."""
    timestamp = meta.timestamp.astimezone(timezone.utc)
    seconds = int(timestamp.timestamp())
    nanos = int(timestamp.microsecond * 1_000)
    return envelope_pb2.EnvelopeMeta(
        envelope_id=meta.envelope_id,
        trace_id=meta.trace_id,
        parent_id=meta.parent_id,
        kind=_kind_to_proto(meta.kind),
        timestamp={"seconds": seconds, "nanos": nanos},
        source=meta.source,
        principal=meta.principal,
    )


def _kind_to_proto(kind: EnvelopeKind) -> envelope_pb2.EnvelopeKind:
    """Map envelope kind enum into protobuf enum value."""
    mapping = {
        EnvelopeKind.UNSPECIFIED: envelope_pb2.ENVELOPE_KIND_UNSPECIFIED,
        EnvelopeKind.COMMAND: envelope_pb2.ENVELOPE_KIND_COMMAND,
        EnvelopeKind.EVENT: envelope_pb2.ENVELOPE_KIND_EVENT,
        EnvelopeKind.RESULT: envelope_pb2.ENVELOPE_KIND_RESULT,
        EnvelopeKind.STREAM: envelope_pb2.ENVELOPE_KIND_STREAM,
    }
    return mapping[kind]


def _health_to_proto(result: CoreHealthResult) -> core_health_pb2.CoreHealthStatus:
    """Convert aggregate core health model to protobuf shape."""
    services = {
        component_id: core_health_pb2.CoreComponentHealthStatus(
            ready=item.ready,
            detail=item.detail,
        )
        for component_id, item in result.services.items()
    }
    resources = {
        component_id: core_health_pb2.CoreComponentHealthStatus(
            ready=item.ready,
            detail=item.detail,
        )
        for component_id, item in result.resources.items()
    }
    return core_health_pb2.CoreHealthStatus(
        ready=result.ready,
        services=services,
        resources=resources,
    )
