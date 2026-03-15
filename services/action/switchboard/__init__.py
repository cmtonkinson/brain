"""Switchboard Service package exports."""

from packages.brain_shared.envelope import Envelope, EnvelopeKind, EnvelopeMeta
from packages.brain_shared.errors import ErrorCategory, ErrorDetail
from services.action.switchboard.boot import (
    register_switchboard_callback_on_boot,
    run_switchboard_boot_hook,
)
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
    RegisterSignalCallbackResult,
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
    "RegisterSignalCallbackResult",
    "SwitchboardIdentitySettings",
    "SwitchboardService",
    "SwitchboardServiceSettings",
    "register_switchboard_callback_on_boot",
    "resolve_switchboard_identity_settings",
    "resolve_switchboard_service_settings",
    "run_switchboard_boot_hook",
]
