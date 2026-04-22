"""Unit tests for MCP output schema override loader."""

from __future__ import annotations

import json
from pathlib import Path

from services.action.capability_engine.mcp_schema_loader import (
    load_mcp_output_schemas,
    resolve_mcp_output_schema,
)


class TestLoadMcpOutputSchemas:
    """load_mcp_output_schemas()."""

    def test_returns_empty_when_dir_missing(self, tmp_path: Path) -> None:
        result = load_mcp_output_schemas(tmp_path)
        assert result == {}

    def test_loads_server_schema(self, tmp_path: Path) -> None:
        schema_dir = tmp_path / "mcp-return-schema"
        schema_dir.mkdir()
        schema = {"type": "object", "properties": {"events": {"type": "array"}}}
        (schema_dir / "eventkit.json").write_text(json.dumps(schema))
        result = load_mcp_output_schemas(tmp_path)
        assert "eventkit" in result
        assert result["eventkit"]["type"] == "object"

    def test_skips_non_dict_json(self, tmp_path: Path) -> None:
        schema_dir = tmp_path / "mcp-return-schema"
        schema_dir.mkdir()
        (schema_dir / "bad.json").write_text(json.dumps([1, 2, 3]))
        result = load_mcp_output_schemas(tmp_path)
        assert result == {}

    def test_skips_non_json_files(self, tmp_path: Path) -> None:
        schema_dir = tmp_path / "mcp-return-schema"
        schema_dir.mkdir()
        (schema_dir / "readme.txt").write_text("not json")
        result = load_mcp_output_schemas(tmp_path)
        assert result == {}

    def test_multiple_servers(self, tmp_path: Path) -> None:
        schema_dir = tmp_path / "mcp-return-schema"
        schema_dir.mkdir()
        (schema_dir / "eventkit.json").write_text(json.dumps({"type": "object"}))
        (schema_dir / "filesystem-rw.json").write_text(json.dumps({"type": "string"}))
        result = load_mcp_output_schemas(tmp_path)
        assert len(result) == 2
        assert "eventkit" in result
        assert "filesystem-rw" in result


class TestResolveMcpOutputSchema:
    """resolve_mcp_output_schema()."""

    def test_found(self) -> None:
        schemas = {"eventkit": {"type": "object"}}
        result = resolve_mcp_output_schema(schemas, "eventkit")
        assert result == {"type": "object"}

    def test_not_found(self) -> None:
        schemas = {"eventkit": {"type": "object"}}
        result = resolve_mcp_output_schema(schemas, "unknown")
        assert result is None

    def test_empty_schemas(self) -> None:
        result = resolve_mcp_output_schema({}, "any")
        assert result is None
