"""Tests for Switchboard service component settings resolution."""

from __future__ import annotations

from lib.shared.config import load_core_runtime_settings
from services.action.switchboard.config import (
    resolve_switchboard_identity_settings,
    resolve_switchboard_service_settings,
)


def test_switchboard_settings_include_callback_registration_defaults() -> None:
    """Resolver should supply default callback-registration settings."""
    settings = load_core_runtime_settings()
    switchboard = resolve_switchboard_service_settings(settings)

    assert switchboard.queue_name == "signal_inbound"
    assert switchboard.callback_register_max_retries == 8
    assert switchboard.callback_register_retry_delay_seconds == 2.0


def test_switchboard_settings_support_callback_registration_env_overrides() -> None:
    """Callback registration settings should honor environment overrides."""
    settings = load_core_runtime_settings(
        environ={
            "BRAIN_CORE_SERVICE__SWITCHBOARD__CALLBACK_REGISTER_MAX_RETRIES": "2",
            "BRAIN_CORE_SERVICE__SWITCHBOARD__CALLBACK_REGISTER_RETRY_DELAY_SECONDS": "0.5",
        }
    )
    switchboard = resolve_switchboard_service_settings(settings)

    assert switchboard.callback_register_max_retries == 2
    assert switchboard.callback_register_retry_delay_seconds == 0.5


def test_resolve_identity_settings_reads_from_core_profile() -> None:
    """Identity resolver must access settings.core.profile, not settings.profile."""
    settings = load_core_runtime_settings()
    identity = resolve_switchboard_identity_settings(settings)

    assert (
        identity.operator_signal_contact_e164
        == settings.core.profile.operator.signal_contact_e164
    )
    assert identity.default_dial_code == settings.core.profile.default_dial_code
