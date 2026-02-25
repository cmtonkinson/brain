"""Attention Router Service package exports."""

from packages.brain_shared.envelope import Envelope, EnvelopeKind, EnvelopeMeta
from packages.brain_shared.errors import ErrorCategory, ErrorDetail
from services.action.attention_router.component import MANIFEST
from services.action.attention_router.config import (
    AttentionRouterServiceSettings,
    resolve_attention_router_service_settings,
)
from services.action.attention_router.domain import (
    ApprovalCorrelationPayload,
    ApprovalNotificationPayload,
    HealthStatus,
    RouteNotificationResult,
    RoutedNotification,
)
from services.action.attention_router.implementation import (
    DefaultAttentionRouterService,
    map_policy_approval_payload,
)
from services.action.attention_router.service import (
    AttentionRouterService,
    build_attention_router_service,
)

__all__ = [
    "ApprovalNotificationPayload",
    "ApprovalCorrelationPayload",
    "AttentionRouterService",
    "AttentionRouterServiceSettings",
    "DefaultAttentionRouterService",
    "Envelope",
    "EnvelopeKind",
    "EnvelopeMeta",
    "ErrorCategory",
    "ErrorDetail",
    "HealthStatus",
    "MANIFEST",
    "RouteNotificationResult",
    "RoutedNotification",
    "build_attention_router_service",
    "map_policy_approval_payload",
    "resolve_attention_router_service_settings",
]
