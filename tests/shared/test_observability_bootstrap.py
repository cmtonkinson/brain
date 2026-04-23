"""Unit tests for shared observability bootstrap helpers."""

from __future__ import annotations

from lib.shared.config import ObservabilitySettings
from lib.shared.observability import bootstrap as bootstrap_module
from lib.shared.observability import (
    bootstrap_observability,
    is_llm_content_capture_enabled,
    is_observability_enabled,
    pydantic_ai_instrumentation_settings,
)


def test_bootstrap_observability_disabled_is_noop() -> None:
    """Disabled observability should not install runtime instrumentation."""
    bootstrap_module._reset_for_tests()

    result = bootstrap_observability(
        settings=ObservabilitySettings(enabled=False),
        service_name="brain-test",
        environment="test",
    )

    assert result.enabled is False
    assert result.traces_enabled is False
    assert result.metrics_enabled is False
    assert result.instrumented_httpx is False
    assert is_observability_enabled() is False
    assert is_llm_content_capture_enabled() is False


def test_pydantic_ai_instrumentation_settings_respects_llm_capture_config() -> None:
    """PydanticAI instrumentation should follow the LLM content-capture switch."""
    bootstrap_module._reset_for_tests()

    disabled = pydantic_ai_instrumentation_settings(
        ObservabilitySettings.model_validate(
            {"enabled": True, "llm": {"enabled": False}}
        )
    )
    enabled = pydantic_ai_instrumentation_settings(
        ObservabilitySettings.model_validate(
            {"enabled": True, "llm": {"capture_content": False}}
        )
    )

    assert disabled is None
    assert enabled is not None
    assert getattr(enabled, "include_content") is False
    assert getattr(enabled, "include_binary_content") is False


def test_otlp_endpoint_adds_signal_suffix_once() -> None:
    """OTLP endpoint helper should accept base or already signal-scoped URLs."""
    assert (
        bootstrap_module._otlp_endpoint("http://otel-collector:4318", "/v1/traces")
        == "http://otel-collector:4318/v1/traces"
    )
    assert (
        bootstrap_module._otlp_endpoint(
            "http://otel-collector:4318/v1/traces", "/v1/traces"
        )
        == "http://otel-collector:4318/v1/traces"
    )
