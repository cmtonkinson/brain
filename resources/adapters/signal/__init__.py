"""Signal adapter resource exports."""

from resources.adapters.signal.adapter import (
    SignalAdapter,
    SignalAdapterDependencyError,
    SignalAdapterError,
    SignalAdapterHealthResult,
    SignalAdapterInternalError,
    SignalSendMessageResult,
    SignalWebhookRegistrationResult,
)
from resources.adapters.signal.component import MANIFEST, RESOURCE_COMPONENT_ID
from resources.adapters.signal.config import (
    SignalAdapterSettings,
    resolve_signal_adapter_settings,
)
from resources.adapters.signal.signal_adapter import HttpSignalAdapter

__all__ = [
    "HttpSignalAdapter",
    "MANIFEST",
    "RESOURCE_COMPONENT_ID",
    "SignalAdapter",
    "SignalAdapterDependencyError",
    "SignalAdapterError",
    "SignalAdapterHealthResult",
    "SignalAdapterInternalError",
    "SignalAdapterSettings",
    "SignalSendMessageResult",
    "SignalWebhookRegistrationResult",
    "resolve_signal_adapter_settings",
]
