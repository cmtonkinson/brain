"""Tests for the slash-help logic skill execute.py."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

_EXECUTE_PATH = (
    Path(__file__).resolve().parents[4] / "capabilities" / "slash-help" / "execute.py"
)


def _load_execute():
    """Load execute function from the slash-help capability package."""
    spec = importlib.util.spec_from_file_location("slash_help_execute", _EXECUTE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.execute


@dataclass(frozen=True, slots=True)
class _Cap:
    capability_id: str
    slash_command_name: str | None = None
    slash_command_aliases: tuple[str, ...] = ()
    slash_command_description: str | None = None
    summary: str = "A capability."
    kind: str = "logic_skill"
    version: str = "1.0.0"
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    autonomy: int = 0
    requires_approval: bool = False
    side_effects: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    simple_output_path: str | None = None


def _run(caps: list[_Cap]) -> str:
    execute = _load_execute()
    client = MagicMock()
    client.describe_capabilities.return_value = tuple(caps)
    with patch("packages.brain_sdk.client.BrainSdkClient", return_value=client):
        return execute()


def test_no_slash_caps_returns_none_registered() -> None:
    assert _run([_Cap(capability_id="demo-echo")]) == "No slash commands registered."


def test_empty_caps_returns_none_registered() -> None:
    assert _run([]) == "No slash commands registered."


def test_single_cap_uses_slash_command_description() -> None:
    result = _run(
        [
            _Cap(
                capability_id="slash-help",
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
                capability_id="slash-help",
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
                capability_id="slash-foo",
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
            _Cap(capability_id="z-cap", slash_command_name="zoo"),
            _Cap(capability_id="a-cap", slash_command_name="apple"),
            _Cap(capability_id="m-cap", slash_command_name="middle"),
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
            _Cap(capability_id="slash-help", slash_command_name="help"),
            _Cap(capability_id="demo-echo"),
        ]
    )
    assert "/help" in result
    assert "demo-echo" not in result


def test_client_error_propagates() -> None:
    import pytest

    execute = _load_execute()
    client = MagicMock()
    client.describe_capabilities.side_effect = RuntimeError("CES unavailable")
    with patch("packages.brain_sdk.client.BrainSdkClient", return_value=client):
        with pytest.raises(RuntimeError, match="CES unavailable"):
            execute()
