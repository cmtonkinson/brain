"""Console adapter resource exports."""

from resources.adapters.console.adapter import (
    ConsoleAdapter,
    ConsoleAdapterError,
    ConsoleAdapterInternalError,
    ConsoleInboundPayload,
)
from resources.adapters.console.component import MANIFEST, RESOURCE_COMPONENT_ID
from resources.adapters.console.config import (
    ConsoleAdapterSettings,
    resolve_console_adapter_settings,
)
from resources.adapters.console.console_adapter import InProcessConsoleAdapter

__all__ = [
    "MANIFEST",
    "RESOURCE_COMPONENT_ID",
    "ConsoleAdapter",
    "ConsoleAdapterError",
    "ConsoleAdapterInternalError",
    "ConsoleAdapterSettings",
    "ConsoleInboundPayload",
    "InProcessConsoleAdapter",
    "resolve_console_adapter_settings",
]
