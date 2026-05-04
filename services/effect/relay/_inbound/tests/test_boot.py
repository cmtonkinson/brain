"""Behavior tests for the Relay boot hook's Signal-disabled short-circuit."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lib.core.boot.contracts import BootContext
from lib.shared.config import (
    CoreRuntimeSettings,
    CoreSettings,
    ResourcesSettings,
)
from services.effect.relay import boot as relay_boot
from services.effect.relay.component import SERVICE_COMPONENT_ID


def _settings_with_signal(receive_e164: str) -> CoreRuntimeSettings:
    """Build a minimal CoreRuntimeSettings with one signal config tweak."""
    component_settings: dict[str, object] = {}
    if receive_e164:
        component_settings["signal"] = {"receive_e164": receive_e164}
    return CoreRuntimeSettings(
        core=CoreSettings.model_validate({}),
        resources=ResourcesSettings.model_validate({}),
        component_settings=component_settings,
    )


def _ctx(settings: CoreRuntimeSettings, relay_service: object) -> BootContext:
    """Build a BootContext that resolves only the relay service."""

    def resolve(component_id: str) -> object | None:
        if component_id == str(SERVICE_COMPONENT_ID):
            return relay_service
        return None

    return BootContext(settings=settings, resolve_component=resolve)


def test_boot_short_circuits_when_receive_e164_is_empty(caplog):
    """receive_e164='' → boot returns without touching the relay service."""
    relay_service = MagicMock(spec_set=["health", "register_signal_callback"])
    settings = _settings_with_signal(receive_e164="")

    with caplog.at_level("INFO", logger="services.effect.relay.boot"):
        relay_boot.boot(_ctx(settings, relay_service))

    relay_service.register_signal_callback.assert_not_called()
    relay_service.health.assert_not_called()
    assert any(
        "signal disabled" in record.getMessage().lower() for record in caplog.records
    )


def test_boot_short_circuits_on_whitespace_only_receive_e164():
    """A whitespace-only number is treated as disabled (validator strips it)."""
    relay_service = MagicMock(spec_set=["health", "register_signal_callback"])
    settings = _settings_with_signal(receive_e164="   ")
    relay_boot.boot(_ctx(settings, relay_service))
    relay_service.register_signal_callback.assert_not_called()


def test_boot_proceeds_past_gate_when_receive_e164_is_set():
    """A real number → boot exits the gate and tries to resolve the relay.

    The full registration loop is covered by the inbound service tests;
    here we only need to prove the Signal-disabled gate doesn't fire when
    the operator opted in. A non-RelayService stand-in causes ``_resolve``
    to raise — we treat that exception as proof the gate let us through.
    """
    relay_service = MagicMock(spec_set=["health", "register_signal_callback"])
    settings = _settings_with_signal(receive_e164="+15551234567")
    with pytest.raises(RuntimeError, match="does not implement RelayService"):
        relay_boot.boot(_ctx(settings, relay_service))


def test_signal_adapter_settings_default_empty():
    """SignalAdapterSettings() now constructs with receive_e164='' default."""
    from resources.adapters.signal.config import SignalAdapterSettings

    settings = SignalAdapterSettings()
    assert settings.receive_e164 == ""
    # Whitespace input is normalized to empty (the validator strips).
    settings_ws = SignalAdapterSettings(receive_e164="  ")
    assert settings_ws.receive_e164 == ""


def test_signal_adapter_settings_preserves_real_number():
    """Non-empty input still passes through unchanged (modulo strip)."""
    from resources.adapters.signal.config import SignalAdapterSettings

    settings = SignalAdapterSettings(receive_e164=" +15551112222 ")
    assert settings.receive_e164 == "+15551112222"
