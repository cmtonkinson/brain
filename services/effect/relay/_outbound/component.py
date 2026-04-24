"""Internal-only identity constant for the Relay's outbound submodule.

Manifest registration lives at ``services.effect.relay.component``.
This module provides a stable ComponentId reference for telemetry and
config resolution under the parent Relay identity.
"""

from __future__ import annotations

from lib.shared.manifest import ComponentId

SERVICE_COMPONENT_ID = ComponentId("service_relay")
