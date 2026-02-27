"""Unit tests for configured OTel naming in public API instrumentation."""

from __future__ import annotations

from packages.brain_shared.config import CoreSettings
from packages.brain_shared.logging import public_api as public_api_module


def test_public_api_otel_names_use_defaults_when_not_configured() -> None:
    """Default OTel names should resolve when observability config is absent."""
    public_api_module._public_api_otel_names.cache_clear()
    names = public_api_module._public_api_otel_names()
    assert names.meter_name == "brain.public_api"
    assert names.tracer_name == "brain.public_api"
    assert names.metric_public_api_calls_total == "brain_public_api_calls_total"


def test_public_api_otel_names_accept_config_overrides(monkeypatch) -> None:
    """Configured OTel names should override built-in defaults."""
    public_api_module._public_api_otel_names.cache_clear()

    def fake_load_core_settings() -> CoreSettings:
        return CoreSettings.model_validate(
            {
                "observability": {
                    "public_api": {
                        "otel": {
                            "meter_name": "custom.meter",
                            "tracer_name": "custom.tracer",
                            "metric_public_api_calls_total": "custom_calls_total",
                        }
                    }
                }
            }
        )

    monkeypatch.setattr(
        public_api_module, "load_core_settings", fake_load_core_settings
    )
    names = public_api_module._public_api_otel_names()
    assert names.meter_name == "custom.meter"
    assert names.tracer_name == "custom.tracer"
    assert names.metric_public_api_calls_total == "custom_calls_total"
