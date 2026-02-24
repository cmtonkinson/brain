"""Switchboard Service package exports."""

from packages.brain_shared.envelope import Envelope, EnvelopeKind, EnvelopeMeta
from packages.brain_shared.errors import ErrorCategory, ErrorDetail
from services.action.switchboard.component import MANIFEST
from services.action.switchboard.config import (
    SwitchboardIdentitySettings,
    SwitchboardServiceSettings,
    resolve_switchboard_identity_settings,
    resolve_switchboard_service_settings,
)
from services.action.switchboard.domain import (
    HealthStatus,
    IngestResult,
    NormalizedSignalMessage,
    RegisterSignalWebhookResult,
)
from services.action.switchboard.implementation import DefaultSwitchboardService
from services.action.switchboard.service import SwitchboardService

__all__ = [
    "DefaultSwitchboardService",
    "Envelope",
    "EnvelopeKind",
    "EnvelopeMeta",
    "ErrorCategory",
    "ErrorDetail",
    "HealthStatus",
    "IngestResult",
    "MANIFEST",
    "NormalizedSignalMessage",
    "RegisterSignalWebhookResult",
    "SwitchboardIdentitySettings",
    "SwitchboardService",
    "SwitchboardServiceSettings",
    "resolve_switchboard_identity_settings",
    "resolve_switchboard_service_settings",
]
