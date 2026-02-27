"""Integration-style UTCP code-mode adapter transposition tests."""

from __future__ import annotations

from resources.adapters.utcp_code_mode import (
    LocalFileUtcpCodeModeAdapter,
    UtcpCodeModeAdapterSettings,
    UtcpOperatorCodeModeDefaults,
    UtcpOperatorCodeModeSection,
)


def _filesystem_settings() -> UtcpCodeModeAdapterSettings:
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


def test_settings_to_config_transposition() -> None:
    """Adapter should transpose inline settings into canonical UTCP config."""
    adapter = LocalFileUtcpCodeModeAdapter(settings=_filesystem_settings())

    loaded = adapter.load()

    assert len(loaded.config.manual_call_templates) == 1
    template = loaded.config.manual_call_templates[0]
    assert template.call_template_type == "mcp"
    assert template.name == "filesystem"


def test_mcp_template_summary_reflects_server_names() -> None:
    """MCP template summary server_names should match the configured server keys."""
    adapter = LocalFileUtcpCodeModeAdapter(settings=_filesystem_settings())

    loaded = adapter.load()

    assert loaded.mcp_templates[0].server_names == ("filesystem",)


def test_multiple_servers_produce_one_template_each() -> None:
    """Each server entry should produce exactly one MCP template."""
    settings = UtcpCodeModeAdapterSettings(
        code_mode=UtcpOperatorCodeModeSection(
            defaults=UtcpOperatorCodeModeDefaults(call_template_type="mcp"),
            servers={
                "alpha": {"command": "npx"},
                "beta": {"command": "uvx"},
            },
        )
    )
    adapter = LocalFileUtcpCodeModeAdapter(settings=settings)

    loaded = adapter.load()

    assert len(loaded.mcp_templates) == 2
    template_names = {t.name for t in loaded.mcp_templates}
    assert template_names == {"alpha", "beta"}
