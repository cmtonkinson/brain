"""Unit tests for self-diagnostic parsing helpers."""

from self_diagnostic_utils import (
    contains_expected_name,
    extract_allowed_directories,
    extract_allowed_directories_from_text,
    extract_code_mode_result,
    parse_code_mode_payload,
)


def test_extract_allowed_directories_from_dict_list() -> None:
    """Extract directories from allowed_directories list payload."""
    value = {"allowed_directories": ["/Users/chris", "/tmp"]}

    assert extract_allowed_directories(value) == ["/Users/chris", "/tmp"]


def test_extract_allowed_directories_from_camelcase() -> None:
    """Extract directories from camelCase keys."""
    value = {"allowedDirectories": ["/Users/chris"]}

    assert extract_allowed_directories(value) == ["/Users/chris"]


def test_extract_allowed_directories_from_content_list() -> None:
    """Extract directories from content list entries."""
    value = {"content": [{"text": "/Users/chris"}, {"text": "/tmp"}]}

    assert extract_allowed_directories(value) == ["/Users/chris", "/tmp"]


def test_extract_allowed_directories_from_list_of_dicts() -> None:
    """Extract directories from list entries containing paths."""
    value = [{"path": "/Users/chris"}, {"directory": "/tmp"}, {"root": "/var"}]

    assert extract_allowed_directories(value) == ["/Users/chris", "/tmp", "/var"]


def test_extract_allowed_directories_from_text() -> None:
    """Extract directories from plain text."""
    value = "Allowed directories:\n- /Users/chris\n- /tmp"

    assert extract_allowed_directories(value) == ["/Users/chris", "/tmp"]


def test_parse_code_mode_payload_json_then_extract() -> None:
    """Parse JSON payload then extract directories."""
    raw = '{"allowedDirectories": ["/Users/chris", "/tmp"]}'

    parsed = parse_code_mode_payload(raw)

    assert extract_allowed_directories(parsed) == ["/Users/chris", "/tmp"]


def test_extract_allowed_directories_from_logs_line() -> None:
    """Extract directories embedded in log lines."""
    text = (
        "Client does not support MCP Roots, "
        "using allowed directories set from server args: [ '/Users/chris' ]"
    )

    assert extract_allowed_directories_from_text(text) == ["/Users/chris"]


def test_contains_expected_name_matches_case_insensitive() -> None:
    """Name matching is case-insensitive."""
    raw = "'Found 1 calendar: Logistics'"

    assert contains_expected_name(raw, "logistics")


def test_contains_expected_name_handles_missing() -> None:
    """Missing names return False."""
    raw = "'Found 1 calendar: Logistics'"

    assert not contains_expected_name(raw, "Other")


def test_extract_code_mode_result_multi_line() -> None:
    """Result extraction returns multi-line values."""
    payload = "\n".join(
        [
            "Logs:",
            "tool log",
            "Result: line1",
            "line2",
            "line3",
        ]
    )

    assert extract_code_mode_result(payload) == "line1\nline2\nline3"


def test_extract_code_mode_result_missing() -> None:
    """Missing Result section returns None."""
    assert extract_code_mode_result("Logs:\nonly logs") is None
