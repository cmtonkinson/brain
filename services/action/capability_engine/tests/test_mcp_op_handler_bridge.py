"""Unit tests for MCP Op handler bridge."""

from __future__ import annotations

import pytest

from services.action.capability_engine.mcp_op_handler_bridge import (
    is_mcp_call_target,
    mcp_capability_id,
    normalize_mcp_content,
    parse_mcp_call_target,
)


class TestParseMcpCallTarget:
    """parse_mcp_call_target()."""

    def test_valid(self) -> None:
        server_id, tool_name = parse_mcp_call_target("mcp:eventkit:list_events")
        assert server_id == "eventkit"
        assert tool_name == "list_events"

    def test_tool_name_with_colons(self) -> None:
        server_id, tool_name = parse_mcp_call_target("mcp:gw:ns:tool")
        assert server_id == "gw"
        assert tool_name == "ns:tool"

    def test_rejects_non_mcp(self) -> None:
        with pytest.raises(ValueError, match="not an MCP"):
            parse_mcp_call_target("service_foo.bar")

    def test_rejects_missing_tool(self) -> None:
        with pytest.raises(ValueError, match="invalid MCP"):
            parse_mcp_call_target("mcp:server:")

    def test_rejects_missing_server(self) -> None:
        with pytest.raises(ValueError, match="invalid MCP"):
            parse_mcp_call_target("mcp::tool")

    def test_rejects_no_parts(self) -> None:
        with pytest.raises(ValueError, match="invalid MCP"):
            parse_mcp_call_target("mcp:only")


class TestIsMcpCallTarget:
    """is_mcp_call_target()."""

    def test_true(self) -> None:
        assert is_mcp_call_target("mcp:s:t") is True

    def test_false(self) -> None:
        assert is_mcp_call_target("service_foo.bar") is False

    def test_empty(self) -> None:
        assert is_mcp_call_target("") is False


class TestMcpCapabilityId:
    """mcp_capability_id()."""

    def test_simple(self) -> None:
        assert mcp_capability_id("eventkit", "list_events") == "eventkit--list-events"

    def test_hyphens_in_tool(self) -> None:
        assert mcp_capability_id("fs", "read-file") == "fs--read-file"

    def test_underscores_normalized(self) -> None:
        assert mcp_capability_id("my_server", "my_tool") == "my-server--my-tool"

    def test_uppercase_lowered(self) -> None:
        assert mcp_capability_id("FS", "ReadFile") == "fs--readfile"

    def test_special_chars_stripped(self) -> None:
        assert mcp_capability_id("fs!", "tool@v2") == "fs--tool-v2"


class TestNormalizeMcpContent:
    """normalize_mcp_content()."""

    def test_empty(self) -> None:
        assert normalize_mcp_content([]) is None

    def test_single_text_plain(self) -> None:
        result = normalize_mcp_content([{"type": "text", "text": "hello world"}])
        assert result == {"text": "hello world"}

    def test_single_text_json_object(self) -> None:
        result = normalize_mcp_content(
            [{"type": "text", "text": '{"events": [1, 2, 3]}'}]
        )
        assert result == {"events": [1, 2, 3]}

    def test_single_text_json_array_not_dict(self) -> None:
        result = normalize_mcp_content([{"type": "text", "text": "[1, 2, 3]"}])
        assert result == {"text": "[1, 2, 3]"}

    def test_multiple_text_items(self) -> None:
        content = [
            {"type": "text", "text": "a"},
            {"type": "text", "text": "b"},
        ]
        result = normalize_mcp_content(content)
        assert result == {"content": content}

    def test_non_text_content(self) -> None:
        content = [{"type": "image", "data": "base64..."}]
        result = normalize_mcp_content(content)
        assert result == {"content": content}

    def test_mixed_content(self) -> None:
        content = [
            {"type": "text", "text": "caption"},
            {"type": "image", "data": "base64..."},
        ]
        result = normalize_mcp_content(content)
        assert result == {"content": content}
