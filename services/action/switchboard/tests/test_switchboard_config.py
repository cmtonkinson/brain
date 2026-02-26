"""Tests for Switchboard service component settings resolution."""

from __future__ import annotations

from packages.brain_shared.config import load_settings
from services.action.switchboard.config import resolve_switchboard_service_settings


def test_switchboard_settings_include_webhook_ingress_defaults() -> None:
    """Resolver should supply default ingress bind/callback settings."""
    settings = load_settings(environ={})
    switchboard = resolve_switchboard_service_settings(settings)

    assert switchboard.webhook_bind_host == "0.0.0.0"
    assert switchboard.webhook_bind_port == 8091
    assert switchboard.webhook_path == "/v1/inbound/signal/webhook"
    assert str(switchboard.webhook_public_base_url) == "http://127.0.0.1:8091"


def test_switchboard_settings_normalize_webhook_path_without_leading_slash() -> None:
    """Webhook path should be canonicalized to a leading-slash absolute path."""
    settings = load_settings(
        environ={"BRAIN_COMPONENTS__SERVICE__SWITCHBOARD__WEBHOOK_PATH": "hooks/signal"}
    )
    switchboard = resolve_switchboard_service_settings(settings)

    assert switchboard.webhook_path == "/hooks/signal"
