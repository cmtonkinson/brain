"""Unit tests for inline-settings UTCP code-mode adapter config generation/loading."""

from __future__ import annotations

import pytest

from resources.adapters.utcp_code_mode import (
    LocalFileUtcpCodeModeAdapter,
    UtcpCodeModeAdapterSettings,
    UtcpOperatorCodeModeDefaults,
    UtcpOperatorCodeModeSection,
)


def _valid_settings() -> UtcpCodeModeAdapterSettings:
    """Return minimum valid adapter settings with one filesystem server."""
    return UtcpCodeModeAdapterSettings(
        code_mode=UtcpOperatorCodeModeSection(
            defaults=UtcpOperatorCodeModeDefaults(call_template_type="mcp"),
            servers={
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                }
            },
        )
    )


def test_adapter_health_is_always_ready() -> None:
    """Inline adapter health should always report ready."""
    adapter = LocalFileUtcpCodeModeAdapter(settings=_valid_settings())
    status = adapter.health()
    assert status.ready is True
    assert status.detail == "ok"


def test_adapter_load_success() -> None:
    """Adapter should build expected canonical config from inline settings."""
    adapter = LocalFileUtcpCodeModeAdapter(settings=_valid_settings())

    result = adapter.load()

    assert len(result.config.manual_call_templates) == 1
    assert len(result.mcp_templates) == 1
    assert result.mcp_templates[0].name == "filesystem"
    assert result.mcp_templates[0].server_names == ("filesystem",)


def test_adapter_load_templates_sorted_by_server_name() -> None:
    """Multiple servers should produce templates in alphabetical order."""
    settings = UtcpCodeModeAdapterSettings(
        code_mode=UtcpOperatorCodeModeSection(
            defaults=UtcpOperatorCodeModeDefaults(call_template_type="mcp"),
            servers={
                "zzz": {"command": "npx"},
                "aaa": {"command": "npx"},
            },
        )
    )
    adapter = LocalFileUtcpCodeModeAdapter(settings=settings)

    result = adapter.load()

    names = [t.name for t in result.mcp_templates]
    assert names == ["aaa", "zzz"]


def test_adapter_load_invalid_mcp_schema_fails() -> None:
    """Empty servers dict should fail schema validation."""
    with pytest.raises(Exception):
        UtcpCodeModeAdapterSettings(
            code_mode=UtcpOperatorCodeModeSection(
                defaults=UtcpOperatorCodeModeDefaults(call_template_type="mcp"),
                servers={},
            )
        )
