"""Tests for the slash-help logic op execute.py."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

_EXECUTE_PATH = (
    Path(__file__).resolve().parents[4] / "ops" / "slash-help" / "execute.py"
)


def _load_execute():
    """Load execute function from the slash-help op package."""
    spec = importlib.util.spec_from_file_location("slash_help_execute", _EXECUTE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.execute


@dataclass(frozen=True, slots=True)
class _Cap:
    op_id: str
    slash_command_name: str | None = None
    slash_command_aliases: tuple[str, ...] = ()
    slash_command_description: str | None = None
    summary: str = "An op."
    kind: str = "logic"
    version: str = "1.0.0"
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    effect: str = "read"
    approval: str = "never"
    required_ops: tuple[str, ...] = ()
    simple_output_path: str | None = None


def _run(caps: list[_Cap], *, query: str | None = None) -> str:
    execute = _load_execute()
    client = MagicMock()
    client.describe_ops.return_value = tuple(caps)
    payload = None if query is None else {"query": query}
    with patch("lib.sdk.client.BrainSdkClient", return_value=client):
        return execute(payload)


def test_no_slash_caps_returns_none_registered() -> None:
    assert _run([_Cap(op_id="demo-echo")]) == "No slash commands registered."


def test_empty_caps_returns_none_registered() -> None:
    assert _run([]) == "No slash commands registered."


def test_single_cap_uses_slash_command_description() -> None:
    result = _run(
        [
            _Cap(
                op_id="slash-help",
                slash_command_name="help",
                slash_command_description="list available slash commands",
            )
        ]
    )
    assert result == "Available commands:\n  /help \u2014 list available slash commands"


def test_single_cap_falls_back_to_summary() -> None:
    result = _run(
        [
            _Cap(
                op_id="slash-help",
                slash_command_name="help",
                summary="Fallback summary.",
            )
        ]
    )
    assert "/help" in result
    assert "Fallback summary." in result


def test_single_cap_with_aliases() -> None:
    result = _run(
        [
            _Cap(
                op_id="slash-foo",
                slash_command_name="foo",
                slash_command_aliases=("f", "fo"),
                slash_command_description="do foo",
            )
        ]
    )
    assert "(aliases: /f, /fo)" in result
    assert "/foo" in result


def test_multiple_caps_sorted_alphabetically() -> None:
    result = _run(
        [
            _Cap(op_id="z-cap", slash_command_name="zoo"),
            _Cap(op_id="a-cap", slash_command_name="apple"),
            _Cap(op_id="m-cap", slash_command_name="middle"),
        ]
    )
    lines = result.splitlines()
    assert lines[0] == "Available commands:"
    assert "/apple" in lines[1]
    assert "/middle" in lines[2]
    assert "/zoo" in lines[3]


def test_non_slash_caps_excluded() -> None:
    result = _run(
        [
            _Cap(op_id="slash-help", slash_command_name="help"),
            _Cap(op_id="demo-echo"),
        ]
    )
    assert "/help" in result
    assert "demo-echo" not in result


def test_client_error_propagates() -> None:
    import pytest

    execute = _load_execute()
    client = MagicMock()
    client.describe_ops.side_effect = RuntimeError("Execution unavailable")
    with patch("lib.sdk.client.BrainSdkClient", return_value=client):
        with pytest.raises(RuntimeError, match="Execution unavailable"):
            execute()


# ---------------------------------------------------------------------------
# Query-driven help (substring + exact match)
# ---------------------------------------------------------------------------


_WORKSPACE_LIST_CAP = _Cap(
    op_id="code-workspace-list",
    slash_command_name="workspaces",
    slash_command_aliases=("workspace-list",),
    slash_command_description="list registered coding workspaces",
)
_WORKSPACE_REGISTER_CAP = _Cap(
    op_id="code-workspace-register",
    slash_command_name="workspace-register",
    slash_command_description="register a coding workspace",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository path."},
            "default_executor": {"type": "string"},
        },
        "required": ["path", "default_executor"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Workspace identifier."},
            "revoked_at": {
                "type": ["string", "null"],
                "description": "Revocation timestamp.",
            },
        },
        "required": ["id"],
    },
    effect="write",
    approval="always",
)
_WORKSPACE_REVOKE_CAP = _Cap(
    op_id="code-workspace-revoke",
    slash_command_name="workspace-revoke",
    slash_command_description="revoke a coding workspace",
)
_OTHER_CAP = _Cap(
    op_id="slash-help",
    slash_command_name="help",
    slash_command_description="list available slash commands",
)


def test_query_substring_filters_to_matches() -> None:
    """Query 'orksp' should narrow the listing to the three workspace ops."""
    result = _run(
        [
            _WORKSPACE_LIST_CAP,
            _WORKSPACE_REGISTER_CAP,
            _WORKSPACE_REVOKE_CAP,
            _OTHER_CAP,
        ],
        query="orksp",
    )
    assert result.startswith("Commands matching 'orksp':")
    assert "/workspaces" in result
    assert "/workspace-register" in result
    assert "/workspace-revoke" in result
    assert "/help" not in result


def test_query_substring_yielding_one_returns_detail() -> None:
    """Query that substring-matches exactly one slash binding returns details."""
    result = _run(
        [
            _WORKSPACE_LIST_CAP,
            _WORKSPACE_REGISTER_CAP,
            _WORKSPACE_REVOKE_CAP,
        ],
        query="workspace-reg",
    )
    assert result.startswith("/workspace-register —")
    assert "Op:      code-workspace-register" in result
    assert "Inputs:" in result
    assert "path (string, required)" in result
    assert "Outputs:" in result
    assert "id (string, required)" in result


def test_query_exact_match_on_alias_returns_detail() -> None:
    """Exact match on an alias should also return the per-op detail view."""
    result = _run(
        [
            _WORKSPACE_LIST_CAP,
            _WORKSPACE_REGISTER_CAP,
        ],
        query="workspace-list",
    )
    assert result.startswith("/workspaces —")
    assert "Aliases: /workspace-list" in result


def test_query_exact_match_on_op_id_returns_detail() -> None:
    """Exact match on the op_id (not the slash name) should return detail."""
    result = _run(
        [_WORKSPACE_REGISTER_CAP, _WORKSPACE_REVOKE_CAP],
        query="code-workspace-revoke",
    )
    assert result.startswith("/workspace-revoke —")
    assert "Op:      code-workspace-revoke" in result


def test_query_no_match_returns_friendly_message() -> None:
    """A query that matches no slash binding should return a guidance message."""
    result = _run(
        [_WORKSPACE_LIST_CAP, _OTHER_CAP],
        query="zzzz-not-a-thing",
    )
    assert "No slash commands match 'zzzz-not-a-thing'" in result


def test_query_is_case_insensitive() -> None:
    """Matching should be case-insensitive on tokens and op_ids."""
    result = _run(
        [_WORKSPACE_REGISTER_CAP, _WORKSPACE_REVOKE_CAP],
        query="REGISTER",
    )
    assert result.startswith("/workspace-register —")


def test_detail_view_renders_default_value_when_present() -> None:
    """Optional fields with a declared default surface that default in the help text."""
    cap = _Cap(
        op_id="demo-defaults",
        slash_command_name="defaults-demo",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repository path.",
                },
                "max_wallclock_seconds": {
                    "type": "integer",
                    "description": "Wallclock budget.",
                    "default": 1800,
                },
                "branch_prefix": {
                    "type": "string",
                    "description": "Branch prefix.",
                    "default": "brain/software/",
                },
            },
            "required": ["path"],
        },
    )
    result = _run([cap], query="defaults-demo")
    assert "path (string, required)" in result
    assert "max_wallclock_seconds (integer, optional, default 1800)" in result
    assert 'branch_prefix (string, optional, default "brain/software/")' in result
