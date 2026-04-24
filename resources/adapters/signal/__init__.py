"""Signal adapter resource exports."""

from resources.adapters.signal.adapter import (
    SignalAdapter,
    SignalCallbackRegistrationResult,
    SignalAdapterDependencyError,
    SignalAdapterError,
    SignalAdapterHealthResult,
    SignalInboundCallback,
    SignalInboundCallbackResult,
    SignalAdapterInternalError,
    SignalSendMessageResult,
)
from resources.adapters.signal.component import MANIFEST, RESOURCE_COMPONENT_ID
from resources.adapters.signal.config import (
    SignalAdapterSettings,
    resolve_signal_adapter_settings,
)
from resources.adapters.signal.signal_adapter import (
    SignalRestApiAdapter,
    summarize_signal_payload,
)

__all__ = [
    "MANIFEST",
    "RESOURCE_COMPONENT_ID",
    "SignalAdapter",
    "SignalCallbackRegistrationResult",
    "SignalAdapterDependencyError",
    "SignalAdapterError",
    "SignalAdapterHealthResult",
    "SignalInboundCallback",
    "SignalInboundCallbackResult",
    "SignalAdapterInternalError",
    "SignalAdapterSettings",
    "SignalSendMessageResult",
    "SignalRestApiAdapter",
    "resolve_signal_adapter_settings",
    "summarize_signal_payload",
]
