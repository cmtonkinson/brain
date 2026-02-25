"""Unit tests for YAML-driven UTCP code-mode adapter config generation/loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resources.adapters.utcp_code_mode import (
    LocalFileUtcpCodeModeAdapter,
    UtcpCodeModeAdapterSettings,
    UtcpCodeModeConfigNotFoundError,
    UtcpCodeModeConfigParseError,
    UtcpCodeModeConfigSchemaError,
)


def _write_utcp_yaml(path: Path, payload: str) -> None:
    """Write one UTF-8 YAML fixture document."""
    path.write_text(payload, encoding="utf-8")


def _valid_utcp_yaml() -> str:
    """Return a minimal valid UTCP YAML fixture."""
    return """
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
""".strip()


def test_adapter_load_success(tmp_path: Path) -> None:
    """Adapter should load valid YAML and generate expected JSON output."""
    yaml_path = tmp_path / "utcp.yaml"
    generated_json_path = tmp_path / "generated-utcp.json"
    _write_utcp_yaml(
        yaml_path,
        _valid_utcp_yaml(),
    )
    adapter = LocalFileUtcpCodeModeAdapter(
        settings=UtcpCodeModeAdapterSettings(
            utcp_yaml_config_path=str(yaml_path),
            generated_utcp_json_path=str(generated_json_path),
        )
    )

    result = adapter.load()

    assert result.generated_json_path == str(generated_json_path)
    assert generated_json_path.exists()
    generated_payload = json.loads(generated_json_path.read_text(encoding="utf-8"))
    assert isinstance(generated_payload, dict)
    assert "manual_call_templates" in generated_payload
    assert len(generated_payload["manual_call_templates"]) == 1
    template_payload = generated_payload["manual_call_templates"][0]
    assert template_payload["name"] == "filesystem"
    assert template_payload["call_template_type"] == "mcp"
    assert template_payload["config"]["mcpServers"]["filesystem"]["command"] == "npx"
    assert len(result.config.manual_call_templates) == 1
    assert len(result.mcp_templates) == 1
    assert result.mcp_templates[0].name == "filesystem"
    assert result.mcp_templates[0].server_names == ("filesystem",)


def test_adapter_load_missing_file_fails(tmp_path: Path) -> None:
    """Missing UTCP YAML path should fail hard."""
    adapter = LocalFileUtcpCodeModeAdapter(
        settings=UtcpCodeModeAdapterSettings(
            utcp_yaml_config_path=str(tmp_path / "missing-utcp.yaml"),
            generated_utcp_json_path=str(tmp_path / "generated-utcp.json"),
        )
    )

    with pytest.raises(UtcpCodeModeConfigNotFoundError):
        adapter.load()


def test_adapter_load_invalid_yaml_fails(tmp_path: Path) -> None:
    """Malformed YAML should fail parse before schema validation."""
    yaml_path = tmp_path / "utcp.yaml"
    _write_utcp_yaml(yaml_path, "code_mode: [")
    adapter = LocalFileUtcpCodeModeAdapter(
        settings=UtcpCodeModeAdapterSettings(
            utcp_yaml_config_path=str(yaml_path),
            generated_utcp_json_path=str(tmp_path / "generated-utcp.json"),
        )
    )

    with pytest.raises(UtcpCodeModeConfigParseError):
        adapter.load()


def test_adapter_load_invalid_mcp_schema_fails(tmp_path: Path) -> None:
    """YAML missing server definitions should fail schema validation."""
    yaml_path = tmp_path / "utcp.yaml"
    _write_utcp_yaml(
        yaml_path,
        """
code_mode:
  defaults:
    call_template_type: mcp
  servers: {}
""".strip(),
    )
    adapter = LocalFileUtcpCodeModeAdapter(
        settings=UtcpCodeModeAdapterSettings(
            utcp_yaml_config_path=str(yaml_path),
            generated_utcp_json_path=str(tmp_path / "generated-utcp.json"),
        )
    )

    with pytest.raises(UtcpCodeModeConfigSchemaError):
        adapter.load()
