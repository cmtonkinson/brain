"""Tests for Switchboard service component settings resolution."""

from __future__ import annotations

from packages.brain_shared.config import load_core_runtime_settings
from services.action.switchboard.config import (
    resolve_switchboard_identity_settings,
    resolve_switchboard_service_settings,
)


def test_switchboard_settings_include_webhook_ingress_defaults() -> None:
    """Resolver should supply default ingress bind/callback settings."""
    settings = load_core_runtime_settings()
    switchboard = resolve_switchboard_service_settings(settings)

    assert switchboard.webhook_bind_host == "0.0.0.0"
    assert switchboard.webhook_bind_port == 8091
    assert switchboard.webhook_path == "/v1/inbound/signal/webhook"
    assert str(switchboard.webhook_public_base_url) == "http://127.0.0.1:8091"


def test_switchboard_settings_normalize_webhook_path_without_leading_slash() -> None:
    """Webhook path should be canonicalized to a leading-slash absolute path."""
    settings = load_core_runtime_settings(
        environ={"BRAIN_CORE_SERVICE__SWITCHBOARD__WEBHOOK_PATH": "hooks/signal"}
    )
    switchboard = resolve_switchboard_service_settings(settings)

    assert switchboard.webhook_path == "/hooks/signal"


def test_resolve_identity_settings_reads_from_core_profile() -> None:
    """Identity resolver must access settings.core.profile, not settings.profile."""
    settings = load_core_runtime_settings()
    identity = resolve_switchboard_identity_settings(settings)

    assert (
        identity.operator_signal_contact_e164
        == settings.core.profile.operator.signal_contact_e164
    )
    assert identity.default_dial_code == settings.core.profile.default_dial_code
    assert identity.webhook_shared_secret == settings.core.profile.webhook_shared_secret
