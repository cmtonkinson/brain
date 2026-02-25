"""Integration-style UTCP code-mode adapter transposition tests."""

from __future__ import annotations

import json

import pytest

from resources.adapters.utcp_code_mode import (
    LocalFileUtcpCodeModeAdapter,
    UtcpCodeModeAdapterSettings,
    UtcpCodeModeConfigNotFoundError,
)


def test_yaml_to_generated_json_roundtrip(tmp_path) -> None:
    """Adapter should transpose operator YAML into canonical generated JSON."""
    source = tmp_path / "utcp.yaml"
    generated = tmp_path / "generated-utcp.json"
    source.write_text(
        """
code_mode:
  defaults:
    call_template_type: mcp
  servers:
    filesystem:
      command: npx
      args:
        - -y
        - "@modelcontextprotocol/server-filesystem"
        - "/tmp"
""".strip(),
        encoding="utf-8",
    )
    adapter = LocalFileUtcpCodeModeAdapter(
        settings=UtcpCodeModeAdapterSettings(
            utcp_yaml_config_path=str(source),
            generated_utcp_json_path=str(generated),
        )
    )

    loaded = adapter.load()
    payload = json.loads(generated.read_text(encoding="utf-8"))

    assert loaded.generated_json_path == str(generated)
    assert payload["manual_call_templates"][0]["call_template_type"] == "mcp"


def test_missing_operator_yaml_fails_hard(tmp_path) -> None:
    """Adapter must fail hard when operator YAML file is missing."""
    adapter = LocalFileUtcpCodeModeAdapter(
        settings=UtcpCodeModeAdapterSettings(
            utcp_yaml_config_path=str(tmp_path / "missing.yaml"),
            generated_utcp_json_path=str(tmp_path / "generated-utcp.json"),
        )
    )

    with pytest.raises(UtcpCodeModeConfigNotFoundError):
        adapter.load()
