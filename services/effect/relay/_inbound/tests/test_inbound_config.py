"""Tests for Relay inbound service component settings resolution."""

from __future__ import annotations

from lib.shared.config import load_core_runtime_settings
from services.effect.relay._inbound.config import (
    resolve_relay_inbound_identity_settings,
    resolve_relay_inbound_service_settings,
)


def test_inbound_settings_include_callback_registration_defaults() -> None:
    """Resolver should supply default callback-registration settings."""
    settings = load_core_runtime_settings()
    inbound = resolve_relay_inbound_service_settings(settings)

    assert inbound.queue_name == "operator_inbound"
    assert inbound.callback_register_max_retries == 8
    assert inbound.callback_register_retry_delay_seconds == 2.0


def test_inbound_settings_support_callback_registration_env_overrides() -> None:
    """Callback registration settings should honor environment overrides under service.relay.inbound."""
    settings = load_core_runtime_settings(
        environ={
            "BRAIN_RELAY__INBOUND__CALLBACK_REGISTER_MAX_RETRIES": "2",
            "BRAIN_RELAY__INBOUND__CALLBACK_REGISTER_RETRY_DELAY_SECONDS": "0.5",
        }
    )
    inbound = resolve_relay_inbound_service_settings(settings)

    assert inbound.callback_register_max_retries == 2
    assert inbound.callback_register_retry_delay_seconds == 0.5


def test_resolve_identity_settings_reads_from_core_profile() -> None:
    """Identity resolver must access settings.core.profile, not settings.profile."""
    settings = load_core_runtime_settings()
    identity = resolve_relay_inbound_identity_settings(settings)

    assert (
        identity.operator_contact_e164
        == settings.core.profile.operator.signal_contact_e164
    )
    assert identity.default_dial_code == settings.core.profile.default_dial_code
