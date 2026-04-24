"""Unit tests for MCP per-tool override loader."""

from __future__ import annotations

import json
from pathlib import Path

from services.effect.execution.mcp_schema_loader import (
    McpToolOverride,
    load_mcp_overrides,
    resolve_mcp_override,
)


class TestLoadMcpOverrides:
    """load_mcp_overrides()."""

    def test_returns_empty_when_dir_missing(self, tmp_path: Path) -> None:
        result = load_mcp_overrides((tmp_path,))
        assert result == {}

    def test_loads_per_tool_overrides(self, tmp_path: Path) -> None:
        overrides_dir = tmp_path / "mcp-overrides"
        overrides_dir.mkdir()
        payload = {
            "list_calendars": {
                "effect": "read",
                "approval": "always",
                "output_schema": {"type": "array"},
            },
            "create_event": {"effect": "write", "approval": "never"},
        }
        (overrides_dir / "eventkit.json").write_text(json.dumps(payload))
        result = load_mcp_overrides((tmp_path,))
        assert "eventkit" in result
        eventkit = result["eventkit"]
        assert eventkit["list_calendars"].effect == "read"
        assert eventkit["list_calendars"].approval == "always"
        assert eventkit["list_calendars"].output_schema == {"type": "array"}
        assert eventkit["create_event"].effect == "write"
        assert eventkit["create_event"].approval == "never"
        assert eventkit["create_event"].output_schema is None

    def test_partial_entry_allowed(self, tmp_path: Path) -> None:
        overrides_dir = tmp_path / "mcp-overrides"
        overrides_dir.mkdir()
        (overrides_dir / "fs.json").write_text(
            json.dumps({"read_file": {"effect": "read"}})
        )
        result = load_mcp_overrides((tmp_path,))
        entry = result["fs"]["read_file"]
        assert entry.effect == "read"
        assert entry.approval is None
        assert entry.output_schema is None

    def test_skips_invalid_field_values(self, tmp_path: Path) -> None:
        overrides_dir = tmp_path / "mcp-overrides"
        overrides_dir.mkdir()
        (overrides_dir / "bad.json").write_text(
            json.dumps({"tool_a": {"effect": "bogus"}, "tool_b": {"effect": "read"}})
        )
        result = load_mcp_overrides((tmp_path,))
        # tool_a is dropped; tool_b survives.
        assert "tool_a" not in result.get("bad", {})
        assert result["bad"]["tool_b"].effect == "read"

    def test_skips_non_dict_root(self, tmp_path: Path) -> None:
        overrides_dir = tmp_path / "mcp-overrides"
        overrides_dir.mkdir()
        (overrides_dir / "list.json").write_text(json.dumps([1, 2, 3]))
        result = load_mcp_overrides((tmp_path,))
        assert result == {}

    def test_skips_non_dict_entries(self, tmp_path: Path) -> None:
        overrides_dir = tmp_path / "mcp-overrides"
        overrides_dir.mkdir()
        (overrides_dir / "mixed.json").write_text(
            json.dumps({"good": {"effect": "read"}, "bad": "not-an-object"})
        )
        result = load_mcp_overrides((tmp_path,))
        assert result["mixed"].keys() == {"good"}

    def test_skips_unknown_extra_fields(self, tmp_path: Path) -> None:
        overrides_dir = tmp_path / "mcp-overrides"
        overrides_dir.mkdir()
        (overrides_dir / "extra.json").write_text(
            json.dumps({"tool": {"effect": "read", "unknown_field": "x"}})
        )
        result = load_mcp_overrides((tmp_path,))
        # Whole entry is dropped because extra=forbid raises validation error.
        assert result.get("extra", {}) == {}

    def test_multiple_servers(self, tmp_path: Path) -> None:
        overrides_dir = tmp_path / "mcp-overrides"
        overrides_dir.mkdir()
        (overrides_dir / "eventkit.json").write_text(
            json.dumps({"list_calendars": {"effect": "read"}})
        )
        (overrides_dir / "filesystem-rw.json").write_text(
            json.dumps({"read_file": {"approval": "always"}})
        )
        result = load_mcp_overrides((tmp_path,))
        assert result["eventkit"]["list_calendars"].effect == "read"
        assert result["filesystem-rw"]["read_file"].approval == "always"

    def test_overlay_later_root_wins_per_tool(self, tmp_path: Path) -> None:
        builtin = tmp_path / "builtin"
        overlay = tmp_path / "overlay"
        (builtin / "mcp-overrides").mkdir(parents=True)
        (overlay / "mcp-overrides").mkdir(parents=True)
        (builtin / "mcp-overrides" / "eventkit.json").write_text(
            json.dumps(
                {
                    "list_calendars": {"effect": "read", "approval": "always"},
                    "create_event": {"effect": "write"},
                }
            )
        )
        (overlay / "mcp-overrides" / "eventkit.json").write_text(
            json.dumps({"list_calendars": {"effect": "external"}})
        )
        result = load_mcp_overrides((builtin, overlay))
        # Overlay wins on conflict, no field-level merging — approval is gone.
        assert result["eventkit"]["list_calendars"].effect == "external"
        assert result["eventkit"]["list_calendars"].approval is None
        # Built-in entry not present in overlay survives untouched.
        assert result["eventkit"]["create_event"].effect == "write"

    def test_overlay_adds_new_servers(self, tmp_path: Path) -> None:
        builtin = tmp_path / "builtin"
        overlay = tmp_path / "overlay"
        (builtin / "mcp-overrides").mkdir(parents=True)
        (overlay / "mcp-overrides").mkdir(parents=True)
        (builtin / "mcp-overrides" / "eventkit.json").write_text(
            json.dumps({"list_calendars": {"effect": "read"}})
        )
        (overlay / "mcp-overrides" / "filesystem.json").write_text(
            json.dumps({"read_file": {"effect": "read"}})
        )
        result = load_mcp_overrides((builtin, overlay))
        assert result["eventkit"]["list_calendars"].effect == "read"
        assert result["filesystem"]["read_file"].effect == "read"

    def test_overlay_skips_missing_root(self, tmp_path: Path) -> None:
        present = tmp_path / "present"
        missing = tmp_path / "missing"  # not created
        (present / "mcp-overrides").mkdir(parents=True)
        (present / "mcp-overrides" / "eventkit.json").write_text(
            json.dumps({"list_calendars": {"effect": "read"}})
        )
        result = load_mcp_overrides((missing, present, missing))
        assert result["eventkit"]["list_calendars"].effect == "read"


class TestResolveMcpOverride:
    """resolve_mcp_override()."""

    def test_found(self) -> None:
        overrides = {"eventkit": {"list_calendars": McpToolOverride(effect="read")}}
        result = resolve_mcp_override(overrides, "eventkit", "list_calendars")
        assert result is not None
        assert result.effect == "read"

    def test_server_missing(self) -> None:
        result = resolve_mcp_override({}, "eventkit", "list_calendars")
        assert result is None

    def test_tool_missing(self) -> None:
        overrides = {"eventkit": {"list_calendars": McpToolOverride(effect="read")}}
        result = resolve_mcp_override(overrides, "eventkit", "create_event")
        assert result is None
